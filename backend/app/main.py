"""FastAPI entrypoint.

Creates tables on startup for the walking skeleton (a real deploy uses Alembic).
Mounts the request flow + meta routers and opens CORS to the Next.js dev origin.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

import asyncio

from starlette.concurrency import run_in_threadpool

from .config import assert_production_secrets, settings
from .db import Base, SessionLocal, engine
from .routers import (
    admin, agent, assistant, auth, contracts, editor, esign, inbound, intake, mailbox, meta, metrics,
    playbook, requests, routing_admin, tabular, workflows,
)

log = logging.getLogger("frontdoor")

app = FastAPI(title="Frontdoor — NDA wedge API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _run_migrations() -> None:
    """Alembic owns the schema. Fresh DB -> build from migrations. A legacy DB
    that predates Alembic (tables exist, no alembic_version) -> stamp head to
    adopt it without recreating. Already-managed DB -> apply new migrations."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    tables = set(inspect(engine).get_table_names())
    root = Path(__file__).resolve().parent.parent  # backend/
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)

    if "alembic_version" in tables:
        command.upgrade(cfg, "head")
    elif "app_user" in tables:
        log.info("adopting existing pre-Alembic schema (stamp head)")
        command.stamp(cfg, "head")
    else:
        command.upgrade(cfg, "head")


def _backfill_demo_auth() -> None:
    """Make an already-seeded DB loginnable: set the demo password on any user
    missing one, and ensure the requester + viewer demo logins exist."""
    from sqlalchemy import select

    from .models import Organization, User
    from .security import hash_password

    db = SessionLocal()
    try:
        org = db.execute(select(Organization)).scalars().first()
        if org is None:
            return
        pw = hash_password(settings.auth_demo_password)
        for u in db.execute(select(User).where(User.password_hash.is_(None))).scalars().all():
            u.password_hash = pw
        existing = {u.email.lower() for u in db.execute(select(User)).scalars().all()}
        for name, email, role in [
            ("Sam Carter", "sam.carter@northwind.example", "requester"),
            ("Val Ng", "val.ng@northwind.example", "viewer"),
        ]:
            if email not in existing:
                db.add(User(org_id=org.id, name=name, email=email, role=role, password_hash=pw))
        db.commit()
    finally:
        db.close()


def _ensure_demo_playbooks() -> None:
    """Give the demo org a SECOND playbook so the multi-playbook switcher and
    per-request selection are demonstrable without a reseed. Idempotent: guarded
    by name, and never touches the default (the new one ships inactive)."""
    from sqlalchemy import select

    from .models import Organization, Playbook, PlaybookRule

    NAME = "Vendor / Procurement NDA (strict)"

    def _rule(pb_id, key, ordinal, ctype, heading, body, rung="none", mandatory=True):
        return PlaybookRule(
            playbook_id=pb_id, rule_key=key, clause_type=ctype, heading=heading, ordinal=ordinal,
            applies_when={}, preferred_position="", preferred_body=body, structured_params={},
            mandatory=mandatory, deviation_rung=rung, rationale="",
        )

    db = SessionLocal()
    try:
        for org in db.execute(select(Organization)).scalars().all():
            exists = db.execute(
                select(Playbook).where(Playbook.org_id == org.id, Playbook.name == NAME)
            ).scalars().first()
            if exists:
                continue
            pb = Playbook(org_id=org.id, name=NAME, version=1, active=False)
            db.add(pb)
            db.flush()
            db.add_all([
                _rule(pb.id, "DEF-01", 1, "confidential_information_definition",
                      "Definition of Confidential Information",
                      "“Confidential Information” means all information disclosed by the Disclosing "
                      "Party, whether or not marked, in connection with {{matter.purpose}}, including "
                      "the existence and terms of this Agreement."),
                _rule(pb.id, "PUR-01", 2, "purpose", "Purpose",
                      "The Receiving Party shall use the Confidential Information solely to perform "
                      "or evaluate services for the Disclosing Party and for no other purpose."),
                _rule(pb.id, "OBL-01", 3, "confidentiality_obligations", "Obligations of Confidentiality",
                      "The Receiving Party shall protect the Confidential Information using no less than "
                      "the same degree of care it uses for its own most sensitive information, and in no "
                      "event less than a high degree of care."),
                _rule(pb.id, "TRM-01", 4, "term", "Term and Survival",
                      "This Agreement remains in effect for twelve (12) months; confidentiality "
                      "obligations survive for five (5) years after disclosure.", rung="vp_legal"),
                _rule(pb.id, "LOL-01", 5, "limitation_of_liability", "Limitation of Liability",
                      "The Receiving Party accepts uncapped liability for any breach of confidentiality; "
                      "no limitation of liability applies to Confidential Information.", rung="gc"),
                _rule(pb.id, "GOV-01", 6, "governing_law", "Governing Law",
                      "This Agreement is governed by the laws of the State of Delaware.", rung="vp_legal"),
                _rule(pb.id, "RET-01", 7, "return_destruction", "Return or Destruction",
                      "Upon request the Receiving Party shall within ten (10) days return or destroy all "
                      "Confidential Information and certify destruction in writing."),
            ])
        db.commit()
    finally:
        db.close()


def _ensure_demo_contracts() -> None:
    """Give the demo org a few executed contracts spanning the renewal lifecycle
    (active / expiring soon / expired) so the Contract registry is demonstrable
    without waiting for real NDAs to age into expiry. Idempotent: guarded by ref,
    and only ever adds — never touches an existing request."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from .models import (
        Counterparty, Direction, Lane, NdaType, Organization, OurRole, Person,
        Request, RequestState,
    )
    from .services.contracts import add_months

    now = datetime.now(timezone.utc)
    # (ref, counterparty, nda_type, purpose, jurisdiction, term_months, executed_at)
    specs = [
        ("NDA-2024-0148", "Meridian Health Systems", NdaType.MUTUAL,
         "vendor_evaluation", "US", 24, now - timedelta(days=63)),        # active
        ("NDA-2023-0092", "Vantage Robotics", NdaType.MUTUAL,
         "partnership_exploration", "US", 24, add_months(now, -23)),      # expiring soon
        ("NDA-2023-0031", "Cobalt Analytics", NdaType.ONE_WAY,
         "sales_evaluation", "US", 12, add_months(now, -14)),            # expired
    ]

    db = SessionLocal()
    try:
        for org in db.execute(select(Organization)).scalars().all():
            requester = db.execute(
                select(Person).where(Person.org_id == org.id)
            ).scalars().first()
            if requester is None:
                requester = Person(org_id=org.id, name="Sam Carter",
                                   email="sam.carter@northwind.example", department="Sales")
                db.add(requester)
                db.flush()
            for ref, cp_name, ndatype, purpose, jx, term, executed in specs:
                existing = db.execute(
                    select(Request).where(Request.org_id == org.id, Request.ref == ref)
                ).scalars().first()
                if existing is not None:
                    # repair rows seeded before the SEED channel marker existed, so
                    # ops_metrics stops counting them as live intake
                    if existing.channel != "SEED":
                        existing.channel = "SEED"
                    continue
                cp = db.execute(
                    select(Counterparty).where(Counterparty.org_id == org.id, Counterparty.name == cp_name)
                ).scalars().first()
                if cp is None:
                    cp = Counterparty(org_id=org.id, name=cp_name)
                    db.add(cp)
                    db.flush()
                db.add(Request(
                    ref=ref, org_id=org.id, type="NDA", direction=Direction.OUTBOUND,
                    nda_type=ndatype, our_role=OurRole.BOTH, state=RequestState.FILED,
                    lane=Lane.AUTO, requester_id=requester.id, counterparty_id=cp.id,
                    purpose=purpose, jurisdiction=jx, term_months=term,
                    # channel="SEED" marks these as pre-platform historical contracts: they
                    # never went through intake, so ops_metrics excludes them from the SLA /
                    # deflection / cycle-time KPIs (they'd otherwise read as instant auto-resolves).
                    channel="SEED",
                    esign_provider="stub", esign_status="completed",
                    created_at=executed, updated_at=executed,
                    executed_at=executed, expires_at=add_months(executed, term),
                ))
        db.commit()
    finally:
        db.close()


def _ensure_request_types_and_ladders() -> None:
    """Startup: seed the default request-type catalog per org (idempotent, respects
    admin edits) and give the standard NDA playbook its position ladders — fallback
    positions + walk-away lines on the three negotiation-heavy rules. Self-healing:
    only fills rules whose ladder is still empty, so lawyer edits survive."""
    from sqlalchemy import select

    from .models import Organization, Playbook, PlaybookRule
    from .services.request_types import ensure_default_request_types

    LADDERS = {
        "TRM-01": {
            "fallbacks": [
                {"label": "36-month term", "rung": "vp_legal",
                 "body": "This Agreement continues for thirty-six (36) months; confidentiality "
                         "obligations survive thirty-six (36) months following disclosure."},
                {"label": "60-month survival for trade secrets", "rung": "vp_legal",
                 "body": "Confidentiality obligations survive sixty (60) months for information "
                         "constituting a trade secret, twenty-four (24) months otherwise."},
            ],
            "walk_away": "A perpetual or indefinite confidentiality term with no survival limit.",
        },
        "LoL-02": {
            "fallbacks": [
                {"label": "24-month fees cap", "rung": "vp_legal",
                 "body": "Aggregate liability shall not exceed the fees paid or payable in the "
                         "twenty-four (24) months preceding the claim; breaches of confidentiality "
                         "obligations remain uncapped."},
            ],
            "walk_away": "Any cap that applies to breaches of confidentiality, or a cap below "
                         "12 months' fees.",
        },
        "GOV-01": {
            "fallbacks": [
                {"label": "New York law", "rung": "vp_legal",
                 "body": "This Agreement is governed by the laws of the State of New York, and the "
                         "parties consent to the exclusive jurisdiction of the courts located there."},
                {"label": "California law", "rung": "vp_legal",
                 "body": "This Agreement is governed by the laws of the State of California, and the "
                         "parties consent to the exclusive jurisdiction of the courts located there."},
            ],
            "walk_away": "Governing law outside the United States, or mandatory arbitration seated "
                         "outside the US.",
        },
    }

    db = SessionLocal()
    try:
        from .services.workflows import ensure_default_workflows

        for org in db.execute(select(Organization)).scalars().all():
            ensure_default_request_types(db, org.id)
            for pb in db.execute(select(Playbook).where(Playbook.org_id == org.id)).scalars().all():
                rules = db.execute(
                    select(PlaybookRule).where(PlaybookRule.playbook_id == pb.id)
                ).scalars().all()
                for rule in rules:
                    ladder = LADDERS.get(rule.rule_key)
                    if ladder and not (rule.fallbacks or []) and not (rule.walk_away_text or "").strip():
                        rule.fallbacks = ladder["fallbacks"]
                        rule.walk_away_text = ladder["walk_away"]
            _ensure_dpa_playbook(db, org.id)
            db.flush()  # request types must exist before workflows key off them
            ensure_default_workflows(db, org.id)
        db.commit()
    finally:
        db.close()


def _ensure_dpa_playbook(db, org_id: str) -> None:
    """Phase 2's proof of generalization: a second CONTRACT engine. Seeds the
    standard DPA playbook (contract_type_key='dpa', active = the DPA default)
    with position ladders on the negotiation-heavy rules. Idempotent by name."""
    from sqlalchemy import select

    from .models import Playbook, PlaybookRule

    NAME = "Standard DPA (controller → processor)"
    if db.execute(
        select(Playbook).where(Playbook.org_id == org_id, Playbook.name == NAME)
    ).scalars().first():
        return

    # become the DPA default only if the org doesn't already have one — an org
    # that built its own active DPA book must not gain a competing default
    has_active_dpa = db.execute(
        select(Playbook).where(
            Playbook.org_id == org_id,
            Playbook.contract_type_key == "dpa",
            Playbook.active == True,  # noqa: E712
        )
    ).scalars().first() is not None
    pb = Playbook(org_id=org_id, name=NAME, contract_type_key="dpa", version=1,
                  active=not has_active_dpa)
    db.add(pb)
    db.flush()

    def rule(key, ordinal, ctype, heading, body, rung="none", mandatory=True,
             fallbacks=None, walk_away=""):
        return PlaybookRule(
            playbook_id=pb.id, rule_key=key, clause_type=ctype, heading=heading,
            ordinal=ordinal, applies_when={}, preferred_position="", preferred_body=body,
            structured_params={}, mandatory=mandatory, deviation_rung=rung, rationale="",
            fallbacks=fallbacks or [], walk_away_text=walk_away,
        )

    db.add_all([
        rule("ROLE-01", 1, "roles_of_parties", "Roles of the Parties",
             "For the purposes of this Agreement, {{org.name}} acts as the Controller and "
             "{{counterparty.name}} acts as the Processor of the Personal Data described in "
             "Annex 1, in connection with {{matter.purpose}}."),
        rule("SCOPE-01", 2, "processing_scope", "Scope and Documented Instructions",
             "The Processor shall process Personal Data only on documented instructions from "
             "the Controller, including with regard to international transfers, and shall "
             "immediately inform the Controller if an instruction infringes applicable data "
             "protection law."),
        rule("SUB-01", 3, "subprocessors", "Sub-processors",
             "The Processor shall not engage a sub-processor without the Controller's prior "
             "written authorisation, and shall impose the obligations of this Agreement on any "
             "authorised sub-processor by written contract.", rung="vp_legal",
             fallbacks=[{"label": "General authorisation with 30-day objection window",
                         "rung": "vp_legal",
                         "body": "The Processor may engage sub-processors under a general written "
                                 "authorisation, provided it gives the Controller thirty (30) days' "
                                 "prior notice of any addition or replacement and the Controller may "
                                 "object on reasonable data-protection grounds."}],
             walk_away="Unrestricted sub-processing with no notice or objection right."),
        rule("SEC-01", 4, "security_measures", "Security Measures",
             "The Processor shall implement and maintain appropriate technical and "
             "organisational measures, including encryption of Personal Data in transit and at "
             "rest, access controls on a need-to-know basis, and regular testing of those "
             "measures.", rung="vp_legal"),
        rule("BRN-01", 5, "breach_notification", "Personal Data Breach Notification",
             "The Processor shall notify the Controller without undue delay and in any event "
             "within twenty-four (24) hours of becoming aware of a Personal Data Breach, "
             "providing sufficient information for the Controller to meet its own notification "
             "obligations.", rung="vp_legal",
             fallbacks=[{"label": "48-hour notification", "rung": "vp_legal",
                         "body": "The Processor shall notify the Controller without undue delay and in "
                                 "any event within forty-eight (48) hours of becoming aware of a "
                                 "Personal Data Breach."},
                        {"label": "72-hour notification (regulatory minimum)", "rung": "gc",
                         "body": "The Processor shall notify the Controller without undue delay and in "
                                 "any event within seventy-two (72) hours of becoming aware of a "
                                 "Personal Data Breach."}],
             walk_away="No breach-notification duty, or notification only 'where feasible'."),
        rule("AUD-01", 6, "audit_rights", "Audit Rights",
             "The Processor shall make available all information necessary to demonstrate "
             "compliance and shall allow for and contribute to audits, including inspections, "
             "conducted by the Controller or its mandated auditor on reasonable notice.",
             rung="vp_legal",
             fallbacks=[{"label": "Third-party reports in lieu (SOC 2 / ISO 27001)",
                         "rung": "vp_legal",
                         "body": "The Processor may satisfy audit requests by providing current SOC 2 "
                                 "Type II or ISO 27001 reports, provided the Controller retains the "
                                 "right to an on-site audit following a Personal Data Breach."}]),
        rule("DSR-01", 7, "data_subject_requests", "Data Subject Requests",
             "Taking into account the nature of the processing, the Processor shall assist the "
             "Controller in responding to data subject requests, forwarding any request it "
             "receives directly within five (5) business days."),
        rule("RET-02", 8, "return_destruction", "Return or Deletion of Personal Data",
             "Upon termination of the services, the Processor shall, at the Controller's "
             "choice, delete or return all Personal Data within thirty (30) days and delete "
             "existing copies unless storage is required by law, certifying deletion in "
             "writing."),
        rule("LOL-03", 9, "limitation_of_liability", "Liability",
             "The Processor's liability for breaches of this Agreement or of applicable data "
             "protection law is not subject to any limitation or exclusion of liability in the "
             "principal agreement.", rung="gc",
             fallbacks=[{"label": "Enhanced cap at 24 months' fees", "rung": "gc",
                         "body": "The Processor's aggregate liability for breaches of this Agreement "
                                 "shall not exceed the fees paid or payable in the twenty-four (24) "
                                 "months preceding the claim."}],
             walk_away="Data-protection liability capped below twelve (12) months' fees, or "
                       "excluded entirely."),
    ])


def _poll_all_sync() -> None:
    """Poll every active mailbox once, in its own DB session (runs in a threadpool
    because imaplib is blocking)."""
    from sqlalchemy import select

    from .models import EmailMailbox
    from .services.email_poller import poll_all_active

    db = SessionLocal()
    try:
        has_active = db.execute(
            select(EmailMailbox.id).where(EmailMailbox.active == True)  # noqa: E712
        ).first()
        if not has_active:
            return
        poll_all_active(db)
    finally:
        db.close()


async def _email_poll_loop() -> None:
    """Background loop: drain configured inboxes on a fixed cadence. Never crashes
    the app — poll errors are logged and recorded on the mailbox row."""
    interval = max(30, settings.email_poll_interval_seconds)
    while True:
        await asyncio.sleep(interval)
        try:
            await run_in_threadpool(_poll_all_sync)
        except Exception:  # noqa: BLE001
            log.exception("email poll loop iteration failed")


@app.on_event("startup")
def _startup() -> None:
    assert_production_secrets()  # fail loud on insecure production config
    _run_migrations()            # Alembic: fresh -> build, legacy -> stamp
    if settings.seed_on_start:
        from .seed import seed

        seed()
    _backfill_demo_auth()
    _ensure_demo_playbooks()
    _ensure_demo_contracts()
    _ensure_request_types_and_ladders()
    if settings.email_polling_enabled:
        asyncio.create_task(_email_poll_loop())  # in-process inbox poller


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    # never leak internals / stack traces to clients
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "frontdoor-api"}


@app.get("/api/health/ready")
def ready() -> dict:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"ok": False, "db": "unavailable"})
    return {"ok": True, "db": "up"}


app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(requests.router)
app.include_router(inbound.router)
app.include_router(intake.router)
app.include_router(esign.router)
app.include_router(playbook.router)
app.include_router(playbook.list_router)
app.include_router(mailbox.router)
app.include_router(metrics.router)
app.include_router(contracts.router)
app.include_router(routing_admin.router)
app.include_router(meta.router)
app.include_router(workflows.router)
app.include_router(assistant.router)
app.include_router(tabular.router)
app.include_router(editor.router)
app.include_router(agent.router)

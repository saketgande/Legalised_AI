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
from .routers import admin, auth, esign, inbound, intake, mailbox, meta, metrics, playbook, requests

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
app.include_router(meta.router)

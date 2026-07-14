"""Centralized intake — every channel (form, email, chatbot) funnels through
here, so classification, triage, generation/redlining, and audit are identical
no matter how the request arrived. The only per-channel difference is *who* the
requester is and *which actor* the audit attributes the intake to.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    ActorType,
    Clause,
    Counterparty,
    Direction,
    Document,
    DocumentVersion,
    Lane,
    NdaType,
    Organization,
    OurRole,
    Person,
    Request,
    RequestState,
)
from .audit import record_audit
from .generation import generate_outbound_nda
from .redline import classify, run_inbound_review, segment
from .triage import triage_outbound


@dataclass
class Actor:
    id: str | None
    type: ActorType
    label: str


# ————————————————————————— shared helpers —————————————————————————
def org_id(db: Session) -> str:
    org = db.execute(select(Organization)).scalars().first()
    if org is None:
        raise RuntimeError("no organisation seeded — run seed.py")
    return org.id


def next_ref(db: Session) -> str:
    count = db.execute(select(func.count(Request.id))).scalar_one()
    return f"REQ-2026-{1000 + count + 1:04d}"


def get_or_create_person(db: Session, org: str, name: str, email: str) -> Person:
    person = db.execute(
        select(Person).where(Person.org_id == org, func.lower(Person.email) == email.lower())
    ).scalars().first()
    if person is None:
        person = Person(org_id=org, name=name, email=email, department="Business")
        db.add(person)
        db.flush()
    return person


def get_or_create_counterparty(db: Session, org: str, name: str) -> Counterparty:
    cp = db.execute(
        select(Counterparty).where(Counterparty.org_id == org, Counterparty.name == name)
    ).scalars().first()
    if cp is None:
        cp = Counterparty(org_id=org, name=name)
        db.add(cp)
        db.flush()
    return cp


# ————————————————————————— advice (the second resolution engine) —————————————————————————
def create_advice(
    db: Session, *, org: str, requester: Person, actor: Actor,
    type_key: str, question: str, channel: str = "FORM", urgency: str = "NORMAL",
) -> Request:
    """The lighter engine: triage -> assign -> governed answer. The requester
    never learns which engine ran — same spine, same tracker, same audit chain."""
    from ..models import RequestCategory, RequestPriority
    from .request_types import get_type
    from .routing import apply_routing_rules

    rtype = get_type(db, org, type_key)
    if rtype is None or not rtype.active:
        raise ValueError(f"unknown request type '{type_key}'")
    if rtype.category != RequestCategory.ADVICE:
        # contract types run the drafting engine — an advice-shaped contract request
        # would have no document, no ladder, and no path to resolution
        raise ValueError(f"'{type_key}' is a contract request type — use the contract intake")

    # advice requests attach to an internal pseudo-counterparty so the spine's
    # FK holds; the UI shows the type label instead
    counterparty = get_or_create_counterparty(db, org, "— internal —")
    prio = urgency if urgency in {p.value for p in RequestPriority} else "NORMAL"
    q = question.strip()
    # purpose doubles as the queue-row subject for advice requests: a readable snippet
    subject = " ".join(q.split())[:90] + ("…" if len(q) > 90 else "")
    r = Request(
        ref=next_ref(db), org_id=org, type=rtype.key, direction=Direction.OUTBOUND,
        state=RequestState.NEW, requester_id=requester.id, counterparty_id=counterparty.id,
        purpose=subject or rtype.key, jurisdiction="US", term_months=0, channel=channel,
        details=q[:8000], priority=RequestPriority(prio),
        sla_target_hours=rtype.default_sla_hours,
    )
    db.add(r)
    db.flush()
    record_audit(
        db, org_id=org, action="request.created", resource_type="Request", resource_id=r.id,
        actor_id=actor.id, actor_type=actor.type, actor_label=actor.label,
        metadata={"type": rtype.key, "channel": channel},
    )
    r.state = RequestState.CLASSIFIED
    record_audit(
        db, org_id=org, action="request.classified", resource_type="Request", resource_id=r.id,
        actor_type=ActorType.AGENT, actor_label="Intake Assistant",
        metadata={"type": rtype.key, "category": rtype.category.value, "channel": channel},
    )
    # advice always gets a human — ASSISTED unless a routing rule escalates
    r.lane = Lane.ASSISTED
    r.triage_reasons = [f"{rtype.label} — routed to the legal queue (SLA {rtype.default_sla_hours}h)."]
    r.state = RequestState.ROUTED
    record_audit(
        db, org_id=org, action="request.routed", resource_type="Request", resource_id=r.id,
        actor_type=ActorType.AGENT, actor_label="Intake Assistant",
        metadata={"lane": r.lane.value, "sla_hours": rtype.default_sla_hours},
    )
    apply_routing_rules(db, r)

    # governed AI draft: a PENDING proposal for the lawyer, never requester-visible
    from .ai import get_ai_client

    draft = get_ai_client().draft_advice_answer(r.details or "", rtype.label)
    if draft:
        r.resolution_draft = draft
        record_audit(
            db, org_id=org, action="advice.draft_proposed", resource_type="Request",
            resource_id=r.id, actor_type=ActorType.AGENT, actor_label="Advice Assistant",
            metadata={"chars": len(draft), "pending_approval": True},
        )
    r.state = RequestState.IN_REVIEW
    record_audit(
        db, org_id=org, action="review.requested", resource_type="Request", resource_id=r.id,
        actor_type=ActorType.SYSTEM, actor_label="System",
        metadata={"engine": "advice"},
    )
    db.commit()
    db.refresh(r)
    return r


# ————————————————————————— outbound —————————————————————————
def create_outbound(
    db: Session, *, org: str, requester: Person, actor: Actor, counterparty_name: str,
    nda_type: str = "MUTUAL", purpose: str = "sales_evaluation", jurisdiction: str = "US",
    term_months: int = 24, channel: str = "FORM", playbook_id: str | None = None,
    renewed_from_id: str | None = None, type_key: str = "nda",
) -> Request:
    from ..models import RequestCategory
    from .playbooks import resolve_playbook
    from .request_types import get_type

    tkey = (type_key or "nda").lower()
    rtype = get_type(db, org, tkey)
    # the founding type stays valid on an unseeded catalog (tests / legacy DBs);
    # every other type must exist as an active CONTRACT catalog entry
    if rtype is None and tkey != "nda":
        raise ValueError(f"'{type_key}' is not an active contract request type")
    if rtype is not None and (not rtype.active or rtype.category != RequestCategory.CONTRACT):
        raise ValueError(f"'{type_key}' is not an active contract request type")
    type_label = rtype.label if rtype else "NDA / confidentiality"

    counterparty = get_or_create_counterparty(db, org, counterparty_name)
    playbook = resolve_playbook(db, org, playbook_id, contract_type=tkey)
    r = Request(
        ref=next_ref(db), org_id=org, type=(rtype.key if rtype else "NDA"),
        direction=Direction.OUTBOUND,
        nda_type=NdaType(nda_type), state=RequestState.NEW, requester_id=requester.id,
        counterparty_id=counterparty.id, purpose=purpose, jurisdiction=jurisdiction,
        term_months=term_months, channel=channel, playbook_id=playbook.id,
        # non-NDA contract types carry their catalog SLA (NDA keeps lane defaults)
        sla_target_hours=None if tkey == "nda" or rtype is None else rtype.default_sla_hours,
        # set the renewal link at creation so it's never committed NULL (closes the
        # crash-consistency gap) and the DB unique index rejects a concurrent double-renew
        renewed_from_id=renewed_from_id,
    )
    db.add(r)
    db.flush()
    record_audit(
        db, org_id=org, action="request.created", resource_type="Request", resource_id=r.id,
        actor_id=actor.id, actor_type=actor.type, actor_label=actor.label,
        metadata={"counterparty": counterparty.name, "channel": channel},
    )
    r.state = RequestState.CLASSIFIED
    record_audit(
        db, org_id=org, action="request.classified", resource_type="Request", resource_id=r.id,
        actor_type=ActorType.AGENT, actor_label="Intake Assistant",
        metadata={"direction": "OUTBOUND", "type": r.type, "channel": channel},
    )
    result = triage_outbound(r, counterparty)
    r.lane = result.lane
    r.triage_reasons = result.reasons
    r.state = RequestState.ROUTED
    record_audit(
        db, org_id=org, action="request.routed", resource_type="Request", resource_id=r.id,
        actor_type=ActorType.AGENT, actor_label="Intake Assistant",
        metadata={"lane": result.lane.value, "reasons": result.reasons},
    )
    from .routing import apply_routing_rules

    fired = apply_routing_rules(db, r)  # admin rules run after triage; may escalate/assign
    generate_outbound_nda(db, r)
    r.state = RequestState.DRAFTED
    doc = db.get(Document, r.document_id)
    version = db.get(DocumentVersion, doc.current_version_id)
    record_audit(
        db, org_id=org, action="document.generated", resource_type="Request", resource_id=r.id,
        actor_type=ActorType.AGENT, actor_label="Playbook Engine",
        metadata={"title": doc.title, "content_hash": version.content_hash},
    )
    # score-driven governance: the drafted round gets a risk assessment, and the
    # per-type band->rungs matrix picks the ladder (no more triage-reason mapping)
    finalize_round_governance(db, r, run=None, escalation_reasons=fired if r.lane == Lane.ESCALATED else [])
    db.commit()
    db.refresh(r)
    return r


# ————————————————————————— inbound —————————————————————————
def create_inbound(
    db: Session, *, org: str, requester: Person, actor: Actor, counterparty_name: str,
    body_text: str, nda_type: str = "MUTUAL", purpose: str = "vendor_evaluation",
    channel: str = "EMAIL", source: str = "paste", playbook_id: str | None = None,
    type_key: str = "nda",
) -> Request:
    from ..models import RequestCategory
    from .playbooks import resolve_playbook
    from .request_types import get_type

    tkey = (type_key or "nda").lower()
    rtype = get_type(db, org, tkey)
    if rtype is None and tkey != "nda":
        raise ValueError(f"'{type_key}' is not an active contract request type")
    if rtype is not None and (not rtype.active or rtype.category != RequestCategory.CONTRACT):
        raise ValueError(f"'{type_key}' is not an active contract request type")
    type_label = rtype.label if rtype else "NDA / confidentiality"

    counterparty = get_or_create_counterparty(db, org, counterparty_name)
    playbook = resolve_playbook(db, org, playbook_id, contract_type=tkey)
    r = Request(
        ref=next_ref(db), org_id=org, type=(rtype.key if rtype else "NDA"),
        direction=Direction.INBOUND,
        nda_type=NdaType(nda_type), our_role=OurRole.RECIPIENT, state=RequestState.NEW,
        requester_id=requester.id, counterparty_id=counterparty.id, purpose=purpose,
        jurisdiction="US", term_months=24, channel=channel, playbook_id=playbook.id,
        sla_target_hours=None if tkey == "nda" or rtype is None else rtype.default_sla_hours,
    )
    db.add(r)
    db.flush()
    record_audit(
        db, org_id=org, action="request.created", resource_type="Request", resource_id=r.id,
        actor_id=actor.id, actor_type=actor.type, actor_label=actor.label,
        metadata={"counterparty": counterparty.name, "direction": "INBOUND", "source": source, "channel": channel},
    )
    record_audit(
        db, org_id=org, action="request.classified", resource_type="Request", resource_id=r.id,
        actor_type=ActorType.AGENT, actor_label="Intake Assistant",
        metadata={"direction": "INBOUND", "type": r.type, "role": "RECIPIENT", "source": source},
    )
    doc = Document(org_id=org, request_id=r.id, origin="UPLOADED",
                   title=f"{counterparty.name} — inbound {type_label} (their paper)")
    db.add(doc)
    db.flush()
    version = DocumentVersion(
        document_id=doc.id, version_no=1, body_markdown=body_text,
        content_hash=hashlib.sha256(body_text.encode("utf-8")).hexdigest(),
        generated_by=f"counterparty-{source}",
    )
    db.add(version)
    db.flush()
    # classify counterparty clauses against THIS playbook's taxonomy: keywords are
    # derived from its own rules (the NDA base map folds in only for NDAs)
    from .playbooks import load_rules
    from .redline import keyword_map_for

    kmap = keyword_map_for(load_rules(db, playbook.id), include_base=(tkey == "nda"))
    for i, (section_no, heading, body) in enumerate(segment(body_text), start=1):
        db.add(Clause(
            document_version_id=version.id, ordinal=i, section_no=section_no or str(i),
            clause_type=classify(heading, body, kmap), heading=heading, body_text=body,
        ))
    doc.current_version_id = version.id
    r.document_id = doc.id
    db.flush()
    from .routing import apply_routing_rules

    fired = apply_routing_rules(db, r)  # inbound reviews route through admin rules too
    run = run_inbound_review(db, r)
    record_audit(
        db, org_id=org, action="review.completed", resource_type="Request", resource_id=r.id,
        actor_type=ActorType.AGENT, actor_label="Redline Engine",
        metadata={"summary": run.summary, "proposed_changes": len(run.changes), "source": source},
    )
    finalize_round_governance(db, r, run=run,
                              escalation_reasons=fired if r.lane == Lane.ESCALATED else [])
    db.commit()
    db.refresh(r)
    return r


def finalize_round_governance(db: Session, r: Request, *, run=None,
                              escalation_reasons: list[str] | None = None,
                              extra_rungs: list[dict] | None = None) -> None:
    """The score-driven governance chokepoint, shared by every round of every
    contract path (outbound draft, inbound review, counterparty returns):

        assess risk -> matrix picks rungs -> build/rebuild the ladder
        -> empty ladder = AUTO (state APPROVED) | steps = IN_REVIEW

    ``escalation_reasons`` (fired routing-rule names) are priced into the score
    so a rule-escalated request can never land in the AUTO lane; ``extra_rungs``
    lets workflow-template rules add steps ([{rung, reason}])."""
    from .approvals import build_ladder_from_risk
    from .request_types import risk_matrix_for
    from .risk import assess_round

    extra_factors = [
        {"label": f"routing rule escalated: {name}", "points": 30, "kind": "DETERMINISTIC"}
        for name in (escalation_reasons or [])
    ]
    assessment = assess_round(db, r, run=run, extra_factors=extra_factors)
    matrix = risk_matrix_for(db, r.org_id, (r.type or "nda").lower())

    forced: list[dict] = list(extra_rungs or [])
    if run is not None and not (matrix.get(assessment.band.value) or forced):
        # their paper never auto-clears, whatever the score says — a human
        # reads it before anything goes back out
        forced.append({"rung": "vp_legal",
                       "reason": "Counterparty paper always gets human review before we respond."})

    ladder = build_ladder_from_risk(db, r, assessment, matrix, extra_rungs=forced)
    if ladder is None:
        if r.lane != Lane.ESCALATED:
            r.lane = Lane.AUTO
        r.state = RequestState.APPROVED
        record_audit(
            db, org_id=r.org_id, action="request.auto_approved", resource_type="Request",
            resource_id=r.id, actor_type=ActorType.AGENT, actor_label="Policy Engine",
            metadata={"round": getattr(r, "round", 1) or 1, "risk_score": assessment.score,
                      "band": assessment.band.value,
                      "reasons": [f["label"] for f in (assessment.factors or [])][:8]
                      or ["on-playbook draft, all facts within policy"]},
        )
    else:
        if r.lane != Lane.ESCALATED:
            r.lane = Lane.ASSISTED
        r.state = RequestState.IN_REVIEW
        record_audit(
            db, org_id=r.org_id, action="review.requested", resource_type="Request",
            resource_id=r.id, actor_type=ActorType.SYSTEM, actor_label="System",
            metadata={"round": getattr(r, "round", 1) or 1, "risk_score": assessment.score,
                      "band": assessment.band.value,
                      "ladder": [s.rung for s in ladder.steps]},
        )


def looks_like_contract(body_text: str) -> bool:
    """Heuristic: does this text look like a contract (vs. a request email)?
    True when segmentation finds several classified clauses."""
    clauses = segment(body_text)
    classified = sum(1 for (_, h, b) in clauses if classify(h, b))
    return len(clauses) >= 3 and classified >= 2


def detect_contract_type(text: str) -> str:
    """Deterministic contract-type detection for the channels with no type
    picker (email, chat). Conservative on purpose: only an explicit DPA ask
    maps to 'dpa' — and misdetection errs SAFE, because non-NDA types can
    never auto-send (the type gate forces attorney review)."""
    import re as _re

    t = text.lower()
    if _re.search(r"\bdpa\b", t) or "data processing agreement" in t or "data processing addendum" in t:
        return "dpa"
    return "nda"

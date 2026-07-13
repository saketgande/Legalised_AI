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
from .approvals import build_ladder
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


# ————————————————————————— outbound —————————————————————————
def create_outbound(
    db: Session, *, org: str, requester: Person, actor: Actor, counterparty_name: str,
    nda_type: str = "MUTUAL", purpose: str = "sales_evaluation", jurisdiction: str = "US",
    term_months: int = 24, channel: str = "FORM", playbook_id: str | None = None,
) -> Request:
    from .playbooks import resolve_playbook

    counterparty = get_or_create_counterparty(db, org, counterparty_name)
    playbook = resolve_playbook(db, org, playbook_id)  # validates + picks default
    r = Request(
        ref=next_ref(db), org_id=org, type="NDA", direction=Direction.OUTBOUND,
        nda_type=NdaType(nda_type), state=RequestState.NEW, requester_id=requester.id,
        counterparty_id=counterparty.id, purpose=purpose, jurisdiction=jurisdiction,
        term_months=term_months, channel=channel, playbook_id=playbook.id,
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
        metadata={"direction": "OUTBOUND", "type": "NDA", "channel": channel},
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
    generate_outbound_nda(db, r)
    r.state = RequestState.DRAFTED
    doc = db.get(Document, r.document_id)
    version = db.get(DocumentVersion, doc.current_version_id)
    record_audit(
        db, org_id=org, action="document.generated", resource_type="Request", resource_id=r.id,
        actor_type=ActorType.AGENT, actor_label="Playbook Engine",
        metadata={"title": doc.title, "content_hash": version.content_hash},
    )
    if result.lane == Lane.AUTO:
        r.state = RequestState.APPROVED
        record_audit(
            db, org_id=org, action="request.auto_approved", resource_type="Request", resource_id=r.id,
            actor_type=ActorType.AGENT, actor_label="Policy Engine", metadata={"reasons": result.reasons},
        )
    else:
        build_ladder(db, r, result.reasons)
        r.state = RequestState.IN_REVIEW
        record_audit(
            db, org_id=org, action="review.requested", resource_type="Request", resource_id=r.id,
            actor_type=ActorType.SYSTEM, actor_label="System",
            metadata={"lane": result.lane.value, "reasons": result.reasons},
        )
    db.commit()
    db.refresh(r)
    return r


# ————————————————————————— inbound —————————————————————————
def create_inbound(
    db: Session, *, org: str, requester: Person, actor: Actor, counterparty_name: str,
    body_text: str, nda_type: str = "MUTUAL", purpose: str = "vendor_evaluation",
    channel: str = "EMAIL", source: str = "paste", playbook_id: str | None = None,
) -> Request:
    from .playbooks import resolve_playbook

    counterparty = get_or_create_counterparty(db, org, counterparty_name)
    playbook = resolve_playbook(db, org, playbook_id)  # validates + picks default
    r = Request(
        ref=next_ref(db), org_id=org, type="NDA", direction=Direction.INBOUND,
        nda_type=NdaType(nda_type), our_role=OurRole.RECIPIENT, state=RequestState.NEW,
        requester_id=requester.id, counterparty_id=counterparty.id, purpose=purpose,
        jurisdiction="US", term_months=24, channel=channel, playbook_id=playbook.id,
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
        metadata={"direction": "INBOUND", "type": "NDA", "role": "RECIPIENT", "source": source},
    )
    doc = Document(org_id=org, request_id=r.id, origin="UPLOADED",
                   title=f"{counterparty.name} — inbound NDA (their paper)")
    db.add(doc)
    db.flush()
    version = DocumentVersion(
        document_id=doc.id, version_no=1, body_markdown=body_text,
        content_hash=hashlib.sha256(body_text.encode("utf-8")).hexdigest(),
        generated_by=f"counterparty-{source}",
    )
    db.add(version)
    db.flush()
    for i, (section_no, heading, body) in enumerate(segment(body_text), start=1):
        db.add(Clause(
            document_version_id=version.id, ordinal=i, section_no=section_no or str(i),
            clause_type=classify(heading, body), heading=heading, body_text=body,
        ))
    doc.current_version_id = version.id
    r.document_id = doc.id
    db.flush()
    run = run_inbound_review(db, r)
    r.state = RequestState.IN_REVIEW
    record_audit(
        db, org_id=org, action="review.completed", resource_type="Request", resource_id=r.id,
        actor_type=ActorType.AGENT, actor_label="Redline Engine",
        metadata={"summary": run.summary, "proposed_changes": len(run.changes), "source": source},
    )
    db.commit()
    db.refresh(r)
    return r


def looks_like_contract(body_text: str) -> bool:
    """Heuristic: does this text look like a contract (vs. a request email)?
    True when segmentation finds several classified clauses."""
    clauses = segment(body_text)
    classified = sum(1 for (_, h, b) in clauses if classify(h, b))
    return len(clauses) >= 3 and classified >= 2

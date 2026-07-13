"""The outbound NDA flow, end to end.

create → classify → triage(route) → generate → [AUTO: auto-approve | ASSISTED:
ladder] → approve → send → simulate-signature → filed. Every transition writes
a hash-chained audit row scoped to the Request, which both the Cockpit timeline
and the requester status view read back.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    ActorType,
    ApprovalStep,
    AuditEvent,
    Clause,
    Counterparty,
    Direction,
    Document,
    DocumentVersion,
    Lane,
    NdaType,
    Person,
    Request,
    RequestState,
    StepStatus,
    User,
)
from ..schemas import (
    ApproveStepIn,
    CreateRequestIn,
    RequestDetailOut,
    RequestSummaryOut,
    RequesterStatusOut,
)
from ..services import esign
from ..services.approvals import all_steps_cleared, build_ladder, ladder_for_request
from ..services.audit import record_audit
from ..services.generation import generate_outbound_nda
from ..services.triage import triage_outbound

router = APIRouter(prefix="/api", tags=["requests"])

AGENT = ActorType.AGENT


# ————————————————————————— helpers —————————————————————————
def _org_id(db: Session) -> str:
    from ..models import Organization

    org = db.execute(select(Organization)).scalars().first()
    if org is None:
        raise HTTPException(500, "no organisation seeded — run seed.py")
    return org.id


def _next_ref(db: Session) -> str:
    count = db.execute(select(func.count(Request.id))).scalar_one()
    return f"REQ-2026-{1000 + count + 1:04d}"


def _get_or_create_person(db: Session, org_id: str, name: str, email: str) -> Person:
    person = db.execute(
        select(Person).where(Person.org_id == org_id, Person.email == email)
    ).scalars().first()
    if person is None:
        person = Person(org_id=org_id, name=name, email=email, department="Business")
        db.add(person)
        db.flush()
    return person


def _get_or_create_counterparty(db: Session, org_id: str, name: str) -> Counterparty:
    cp = db.execute(
        select(Counterparty).where(Counterparty.org_id == org_id, Counterparty.name == name)
    ).scalars().first()
    if cp is None:
        cp = Counterparty(org_id=org_id, name=name)
        db.add(cp)
        db.flush()
    return cp


_STAGE = {  # state -> (label, index 0..4, needs_you)
    RequestState.NEW: ("Requested", 0),
    RequestState.CLASSIFIED: ("Requested", 0),
    RequestState.ROUTED: ("Requested", 0),
    RequestState.DRAFTED: ("Drafting", 1),
    RequestState.IN_REVIEW: ("In review", 2),
    RequestState.APPROVED: ("In review", 2),
    RequestState.OUT_FOR_SIGNATURE: ("Sent to counterparty", 3),
    RequestState.EXECUTED: ("Signed", 4),
    RequestState.FILED: ("Signed", 4),
    RequestState.CANCELLED: ("Cancelled", 0),
}


def _timeline(db: Session, request_id: str) -> list[dict]:
    rows = db.execute(
        select(AuditEvent)
        .where(AuditEvent.resource_id == request_id)
        .order_by(AuditEvent.chain_position.asc())
    ).scalars().all()
    return [
        {
            "chain_position": r.chain_position,
            "action": r.action,
            "actor_type": r.actor_type.value,
            "actor_label": r.actor_label,
            "metadata": r.metadata_json,
            "created_at": r.created_at,
        }
        for r in rows
    ]


def _open_steps(db: Session, request_id: str) -> int:
    """Open work items: pending ladder steps (outbound) + pending proposed
    changes (inbound)."""
    from ..services.redline import latest_run

    count = 0
    ladder = ladder_for_request(db, request_id)
    if ladder is not None:
        count += sum(1 for s in ladder.steps if s.status == StepStatus.PENDING)
    run = latest_run(db, request_id)
    if run is not None:
        count += sum(1 for c in run.changes if c.decision == "PENDING")
    return count


def _summary(db: Session, r: Request) -> dict:
    cp = db.get(Counterparty, r.counterparty_id)
    person = db.get(Person, r.requester_id)
    return {
        "id": r.id,
        "ref": r.ref,
        "type": r.type,
        "direction": r.direction.value,
        "nda_type": r.nda_type.value,
        "state": r.state.value,
        "lane": r.lane.value if r.lane else None,
        "counterparty_name": cp.name if cp else "—",
        "requester_name": person.name if person else "—",
        "purpose": r.purpose,
        "jurisdiction": r.jurisdiction,
        "term_months": r.term_months,
        "created_at": r.created_at,
        "open_steps": _open_steps(db, r.id),
    }


def _document_out(db: Session, r: Request) -> dict | None:
    if not r.document_id:
        return None
    doc = db.get(Document, r.document_id)
    if doc is None or not doc.current_version_id:
        return None
    version = db.get(DocumentVersion, doc.current_version_id)
    clauses = db.execute(
        select(Clause)
        .where(Clause.document_version_id == version.id)
        .order_by(Clause.ordinal.asc())
    ).scalars().all()
    return {
        "id": doc.id,
        "title": doc.title,
        "origin": doc.origin,
        "version_no": version.version_no,
        "content_hash": version.content_hash,
        "body_markdown": version.body_markdown,
        "clauses": [
            {
                "id": c.id,
                "ordinal": c.ordinal,
                "section_no": c.section_no,
                "clause_type": c.clause_type,
                "heading": c.heading,
                "body_text": c.body_text,
                "source_rule_key": c.source_rule_key,
            }
            for c in clauses
        ],
    }


def _ladder_out(db: Session, request_id: str) -> dict | None:
    ladder = ladder_for_request(db, request_id)
    if ladder is None:
        return None
    steps = []
    for s in ladder.steps:
        assignee = db.get(User, s.assignee_user_id) if s.assignee_user_id else None
        steps.append(
            {
                "id": s.id,
                "ordinal": s.ordinal,
                "rung": s.rung,
                "reason": s.reason,
                "status": s.status.value,
                "assignee_name": assignee.name if assignee else None,
                "decided_by": s.decided_by,
                "decided_at": s.decided_at,
            }
        )
    return {"id": ladder.id, "status": ladder.status, "steps": steps}


def _review_out(db: Session, r: Request) -> dict | None:
    from ..services.redline import build_counter_markdown, latest_run, required_rungs

    run = latest_run(db, r.id)
    if run is None:
        return None
    return {
        "id": run.id,
        "status": run.status,
        "summary": run.summary or {},
        "changes": [
            {
                "id": c.id,
                "ordinal": c.ordinal,
                "section_no": c.section_no,
                "heading": c.heading,
                "finding": c.finding,
                "rule_key": c.rule_key,
                "before_text": c.before_text,
                "after_text": c.after_text,
                "rationale": c.rationale,
                "checks": c.checks or [],
                "confidence": c.confidence,
                "triggered_rung": c.triggered_rung,
                "decision": c.decision,
            }
            for c in run.changes
        ],
        "counter_markdown": build_counter_markdown(db, r, run),
        "required_rungs": required_rungs(run),
    }


def _detail(db: Session, r: Request) -> dict:
    base = _summary(db, r)
    base.update(
        {
            "triage_reasons": r.triage_reasons or [],
            "document": _document_out(db, r),
            "ladder": _ladder_out(db, r.id),
            "review": _review_out(db, r),
            "timeline": _timeline(db, r.id),
        }
    )
    return base


# ————————————————————————— endpoints —————————————————————————
@router.post("/requests", response_model=RequestDetailOut)
def create_request(payload: CreateRequestIn, db: Session = Depends(get_db)):
    org_id = _org_id(db)
    requester = _get_or_create_person(db, org_id, payload.requester_name, payload.requester_email)
    counterparty = _get_or_create_counterparty(db, org_id, payload.counterparty_name)

    r = Request(
        ref=_next_ref(db),
        org_id=org_id,
        type="NDA",
        direction=Direction.OUTBOUND,
        nda_type=NdaType(payload.nda_type),
        state=RequestState.NEW,
        requester_id=requester.id,
        counterparty_id=counterparty.id,
        purpose=payload.purpose,
        jurisdiction=payload.jurisdiction,
        term_months=payload.term_months,
        channel=payload.channel,
    )
    db.add(r)
    db.flush()
    record_audit(
        db, org_id=org_id, action="request.created", resource_type="Request", resource_id=r.id,
        actor_id=requester.id, actor_type=ActorType.USER, actor_label=requester.name,
        metadata={"counterparty": counterparty.name, "channel": payload.channel},
    )

    # classify (this slice: outbound, on our paper)
    r.state = RequestState.CLASSIFIED
    record_audit(
        db, org_id=org_id, action="request.classified", resource_type="Request", resource_id=r.id,
        actor_type=AGENT, actor_label="Intake Assistant",
        metadata={"direction": "OUTBOUND", "type": "NDA"},
    )

    # triage / route
    result = triage_outbound(r, counterparty)
    r.lane = result.lane
    r.triage_reasons = result.reasons
    r.state = RequestState.ROUTED
    record_audit(
        db, org_id=org_id, action="request.routed", resource_type="Request", resource_id=r.id,
        actor_type=AGENT, actor_label="Intake Assistant",
        metadata={"lane": result.lane.value, "reasons": result.reasons},
    )

    # generate from playbook
    generate_outbound_nda(db, r)
    r.state = RequestState.DRAFTED
    doc = db.get(Document, r.document_id)
    version = db.get(DocumentVersion, doc.current_version_id)
    record_audit(
        db, org_id=org_id, action="document.generated", resource_type="Request", resource_id=r.id,
        actor_type=AGENT, actor_label="Playbook Engine",
        metadata={"title": doc.title, "content_hash": version.content_hash},
    )

    # lane fork
    if result.lane == Lane.AUTO:
        r.state = RequestState.APPROVED
        record_audit(
            db, org_id=org_id, action="request.auto_approved", resource_type="Request", resource_id=r.id,
            actor_type=AGENT, actor_label="Policy Engine",
            metadata={"reasons": result.reasons},
        )
    else:
        build_ladder(db, r, result.reasons)
        r.state = RequestState.IN_REVIEW
        record_audit(
            db, org_id=org_id, action="review.requested", resource_type="Request", resource_id=r.id,
            actor_type=ActorType.SYSTEM, actor_label="System",
            metadata={"lane": result.lane.value, "reasons": result.reasons},
        )

    db.commit()
    db.refresh(r)
    return _detail(db, r)


@router.get("/requests", response_model=list[RequestSummaryOut])
def list_requests(state: str | None = None, lane: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Request).order_by(Request.created_at.desc())
    if state:
        stmt = stmt.where(Request.state == RequestState(state))
    if lane:
        stmt = stmt.where(Request.lane == Lane(lane))
    rows = db.execute(stmt).scalars().all()
    return [_summary(db, r) for r in rows]


@router.get("/requests/{request_id}", response_model=RequestDetailOut)
def get_request(request_id: str, db: Session = Depends(get_db)):
    r = db.get(Request, request_id)
    if r is None:
        raise HTTPException(404, "request not found")
    return _detail(db, r)


@router.get("/requests/{request_id}/status", response_model=RequesterStatusOut)
def requester_status(request_id: str, db: Session = Depends(get_db)):
    r = db.get(Request, request_id)
    if r is None:
        raise HTTPException(404, "request not found")
    cp = db.get(Counterparty, r.counterparty_id)
    label, idx = _STAGE.get(r.state, ("Requested", 0))

    if r.state in (RequestState.IN_REVIEW,):
        headline = "Being reviewed by legal — nothing needed from you."
        detail = "A lawyer is checking a couple of terms before it goes out. Typically cleared within a day."
    elif r.state == RequestState.APPROVED:
        headline = "Cleared review — sending to the counterparty."
        detail = "Your NDA is approved and about to be sent for signature."
    elif r.state == RequestState.OUT_FOR_SIGNATURE:
        headline = f"Sent to {cp.name} for signature."
        detail = "We'll drop the signed copy here as soon as it's countersigned."
    elif r.state in (RequestState.EXECUTED, RequestState.FILED):
        headline = f"Signed by {cp.name} — you're all set."
        detail = "The executed NDA is filed and its renewal date is being tracked."
    else:
        headline = "Your NDA is being drafted."
        detail = "We're assembling it from the approved template. This is usually instant."

    return {
        "ref": r.ref,
        "counterparty_name": cp.name if cp else "—",
        "nda_type": r.nda_type.value,
        "purpose": r.purpose,
        "stage": label,
        "stage_index": idx,
        "needs_you": False,
        "headline": headline,
        "detail": detail,
        "document_ready": r.state in (RequestState.EXECUTED, RequestState.FILED),
        "timeline": _timeline(db, r.id),
    }


@router.post("/approvals/steps/{step_id}/approve", response_model=RequestDetailOut)
def approve_step(step_id: str, payload: ApproveStepIn, db: Session = Depends(get_db)):
    step = db.get(ApprovalStep, step_id)
    if step is None:
        raise HTTPException(404, "approval step not found")
    if step.status != StepStatus.PENDING:
        raise HTTPException(409, "step already decided")

    ladder = step.ladder
    r = db.get(Request, ladder.request_id)
    approver = db.get(User, payload.user_id) if payload.user_id else db.get(User, step.assignee_user_id)

    step.status = StepStatus.APPROVED
    step.decided_by = approver.id if approver else None
    step.decided_at = datetime.now(timezone.utc)
    record_audit(
        db, org_id=r.org_id, action="ladder.step.approved", resource_type="Request", resource_id=r.id,
        actor_id=approver.id if approver else None, actor_type=ActorType.USER,
        actor_label=approver.name if approver else "Reviewer",
        metadata={"rung": step.rung, "reason": step.reason},
    )

    db.refresh(ladder)
    if all_steps_cleared(ladder):
        ladder.status = "APPROVED"
        r.state = RequestState.APPROVED
        record_audit(
            db, org_id=r.org_id, action="request.approved", resource_type="Request", resource_id=r.id,
            actor_id=approver.id if approver else None, actor_type=ActorType.USER,
            actor_label=approver.name if approver else "Reviewer",
            metadata={"steps": len(ladder.steps)},
        )
    db.commit()
    db.refresh(r)
    return _detail(db, r)


@router.post("/requests/{request_id}/send", response_model=RequestDetailOut)
def send_request(request_id: str, db: Session = Depends(get_db)):
    r = db.get(Request, request_id)
    if r is None:
        raise HTTPException(404, "request not found")
    if r.state != RequestState.APPROVED:
        raise HTTPException(409, f"request must be APPROVED to send (is {r.state.value})")
    cp = db.get(Counterparty, r.counterparty_id)
    doc = db.get(Document, r.document_id)
    envelope = esign.send_for_signature(doc.title if doc else r.ref, cp.name if cp else "counterparty")
    r.state = RequestState.OUT_FOR_SIGNATURE
    record_audit(
        db, org_id=r.org_id, action="request.sent", resource_type="Request", resource_id=r.id,
        actor_type=ActorType.SYSTEM, actor_label="System",
        metadata={"envelope_id": envelope["envelope_id"], "recipient": envelope["recipient"]},
    )
    db.commit()
    db.refresh(r)
    return _detail(db, r)


@router.post("/requests/{request_id}/simulate-signature", response_model=RequestDetailOut)
def simulate_signature(request_id: str, db: Session = Depends(get_db)):
    """Stands in for the counterparty countersigning (dev only)."""
    r = db.get(Request, request_id)
    if r is None:
        raise HTTPException(404, "request not found")
    if r.state != RequestState.OUT_FOR_SIGNATURE:
        raise HTTPException(409, f"request is not out for signature (is {r.state.value})")
    cp = db.get(Counterparty, r.counterparty_id)
    r.state = RequestState.EXECUTED
    record_audit(
        db, org_id=r.org_id, action="request.executed", resource_type="Request", resource_id=r.id,
        actor_type=ActorType.SYSTEM, actor_label="E-Sign (stub)",
        metadata={"countersigned_by": cp.name if cp else "counterparty"},
    )
    r.state = RequestState.FILED
    record_audit(
        db, org_id=r.org_id, action="request.filed", resource_type="Request", resource_id=r.id,
        actor_type=ActorType.SYSTEM, actor_label="System",
        metadata={"renewal_tracked": True, "expires_in_months": r.term_months},
    )
    db.commit()
    db.refresh(r)
    return _detail(db, r)

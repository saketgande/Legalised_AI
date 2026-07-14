"""The outbound NDA flow, end to end.

create → classify → triage(route) → generate → [AUTO: auto-approve | ASSISTED:
ladder] → approve → send → simulate-signature → filed. Every transition writes
a hash-chained audit row scoped to the Request, which both the Cockpit timeline
and the requester status view read back.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
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
from ..config import settings
from ..permissions import ASSIGNABLE_ROLES, Permission, can
from ..schemas import (
    ApproveStepIn,
    AssignIn,
    BulkActionIn,
    CounterpartyReturnIn,
    CreateAdviceIn,
    CreateRequestIn,
    RequestDetailOut,
    RequestSummaryOut,
    RequesterStatusOut,
    ResolveAdviceIn,
    SnoozeIn,
)
from ..security import assert_can_clear_rung, current_user, require
from ..services import esign
from ..services.approvals import all_steps_cleared, build_ladder, ladder_for_request
from ..services.audit import record_audit
from ..services.contracts import stamp_execution
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


def _owns(db: Session, user: User, r: Request) -> bool:
    person = db.get(Person, r.requester_id)
    return person is not None and person.email.lower() == user.email.lower()


def _authorize_read(db: Session, user: User, r: Request) -> None:
    if r.org_id != user.org_id:
        raise HTTPException(404, "request not found")  # cross-org ids don't exist for you
    if can(user.role, Permission.REQUEST_READ_ALL):
        return
    if can(user.role, Permission.REQUEST_READ_OWN) and _owns(db, user, r):
        return
    raise HTTPException(403, "not permitted to read this request")


def _authorize_org_write(user: User, r: Request | None) -> Request:
    """Shared org guard for mutation endpoints: foreign-org ids read as 404."""
    if r is None or r.org_id != user.org_id:
        raise HTTPException(404, "request not found")
    return r


def _require_queue_ops(user: User) -> None:
    """Queue operations (assign / snooze / bulk) are for reviewers AND intake
    managers — legal_ops runs the queue without holding review:decide."""
    if not (can(user.role, Permission.REVIEW_DECIDE) or can(user.role, Permission.INTAKE_MANAGE)):
        raise HTTPException(403, "not permitted to manage the queue")


def _validate_assignee(db: Session, user: User, user_id: str) -> User:
    assignee = db.get(User, user_id)
    if assignee is None or assignee.org_id != user.org_id or assignee.suspended \
            or assignee.role not in ASSIGNABLE_ROLES:
        raise HTTPException(400, "assignee must be an active legal-staff user in your organisation")
    return assignee


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
    RequestState.WITH_COUNTERPARTY: ("Sent to counterparty", 3),
    RequestState.RETURNED: ("In review", 2),
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


def _type_info(db: Session, r: Request) -> tuple[str | None, str]:
    """(catalog label, category) for the request's type. Legacy 'NDA' rows map to
    the 'nda' catalog entry; unknown keys read as CONTRACT so old flows keep working."""
    from ..services.request_types import get_type

    rt = get_type(db, r.org_id, (r.type or "nda").lower())
    if rt is None:
        return None, "CONTRACT"
    return rt.label, rt.category.value


def _summary(db: Session, r: Request) -> dict:
    from ..models import Playbook
    from ..services.risk import latest_assessment

    cp = db.get(Counterparty, r.counterparty_id)
    person = db.get(Person, r.requester_id)
    pb = db.get(Playbook, r.playbook_id) if r.playbook_id else None
    assignee = db.get(User, r.assigned_to_user_id) if r.assigned_to_user_id else None
    type_label, category = _type_info(db, r)
    risk = latest_assessment(db, r.id)
    return {
        "id": r.id,
        "ref": r.ref,
        "type": r.type,
        "type_label": type_label,
        "category": category,
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
        "priority": r.priority.value if r.priority else "NORMAL",
        "assigned_to_user_id": r.assigned_to_user_id,
        "assigned_to_name": assignee.name if assignee else None,
        "snoozed_until": r.snoozed_until,
        "sla_target_hours": r.sla_target_hours,
        "playbook_id": r.playbook_id,
        "playbook_name": pb.name if pb else None,
        "playbook_version": pb.version if pb else None,
        "esign_provider": r.esign_provider,
        "esign_status": r.esign_status,
        "esign_envelope_id": r.esign_envelope_id,
        "round": r.round or 1,
        "risk_band": risk.band.value if risk else None,
        "risk_score": risk.score if risk else None,
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


def _risk_out(a) -> dict:
    return {
        "round": a.round, "score": a.score, "band": a.band.value,
        "factors": a.factors or [], "ai_adjustment": a.ai_adjustment,
        "ai_note": a.ai_note or "", "model": a.model, "created_at": a.created_at,
    }


def _detail(db: Session, r: Request, user: User | None = None) -> dict:
    from ..services.risk import assessment_history

    # The AI's PENDING answer proposal is reviewer-eyes-only: it must never reach
    # the requester before approval. Default (no user passed) is hide.
    show_draft = user is not None and can(user.role, Permission.REVIEW_DECIDE)
    history = assessment_history(db, r.id)
    base = _summary(db, r)
    base.update(
        {
            "triage_reasons": r.triage_reasons or [],
            "document": _document_out(db, r),
            "ladder": _ladder_out(db, r.id),
            "review": _review_out(db, r),
            "timeline": _timeline(db, r.id),
            "details": r.details,
            "resolution_draft": r.resolution_draft if show_draft else None,
            "resolution_note": r.resolution_note,
            "risk": _risk_out(history[-1]) if history else None,
            "risk_history": [_risk_out(a) for a in history],
            "workflow": _workflow_out(db, r),
        }
    )
    return base


def _workflow_out(db: Session, r: Request) -> dict | None:
    if not (r.workflow_rungs or []):
        return None
    from ..models import WorkflowTemplate

    tpl = db.get(WorkflowTemplate, r.workflow_template_id) if r.workflow_template_id else None
    return {
        "template_name": tpl.name if tpl else None,
        "version": r.workflow_version,
        "rungs": r.workflow_rungs or [],
    }


# ————————————————————————— endpoints —————————————————————————
@router.post("/requests", response_model=RequestDetailOut)
def create_request(
    payload: CreateRequestIn,
    user: User = Depends(require(Permission.REQUEST_CREATE)),
    db: Session = Depends(get_db),
):
    from ..services import intake
    from ..services.playbooks import PlaybookResolutionError

    # the requester is the authenticated user (attribution is real, not free-text)
    requester = intake.get_or_create_person(db, user.org_id, user.name, user.email)
    try:
        r = intake.create_outbound(
            db, org=user.org_id, requester=requester,
            actor=intake.Actor(user.id, ActorType.USER, user.name),
            counterparty_name=payload.counterparty_name, nda_type=payload.nda_type,
            purpose=payload.purpose, jurisdiction=payload.jurisdiction,
            term_months=payload.term_months, channel=payload.channel,
            playbook_id=payload.playbook_id, type_key=payload.type_key,
        )
    except (PlaybookResolutionError, ValueError) as e:
        raise HTTPException(400, str(e))
    return _detail(db, r)


@router.post("/requests/advice", response_model=RequestDetailOut)
def create_advice_request(
    payload: CreateAdviceIn,
    user: User = Depends(require(Permission.REQUEST_CREATE)),
    db: Session = Depends(get_db),
):
    """File an ADVICE-category request (legal question, marketing review, …).
    Same spine, lighter engine: triage -> assign -> governed answer."""
    from ..services import intake

    if not payload.question.strip():
        raise HTTPException(400, "the question / details are required")
    requester = intake.get_or_create_person(db, user.org_id, user.name, user.email)
    try:
        r = intake.create_advice(
            db, org=user.org_id, requester=requester,
            actor=intake.Actor(user.id, ActorType.USER, user.name),
            type_key=payload.type_key, question=payload.question,
            channel=payload.channel, urgency=payload.urgency,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _detail(db, r)


@router.post("/requests/{request_id}/assign", response_model=RequestDetailOut)
def assign_request(
    request_id: str, payload: AssignIn,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    _require_queue_ops(user)
    r = _authorize_org_write(user, db.get(Request, request_id))
    assignee = _validate_assignee(db, user, payload.user_id) if payload.user_id else None
    before = r.assigned_to_user_id
    r.assigned_to_user_id = assignee.id if assignee else None
    record_audit(
        db, org_id=r.org_id, action="request.assigned" if assignee else "request.unassigned",
        resource_type="Request", resource_id=r.id,
        actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"from": before, "to": r.assigned_to_user_id,
                  "assignee": assignee.name if assignee else None},
    )
    db.commit()
    db.refresh(r)
    return _detail(db, r, user)


@router.post("/requests/{request_id}/snooze", response_model=RequestDetailOut)
def snooze_request(
    request_id: str, payload: SnoozeIn,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    from datetime import timedelta

    _require_queue_ops(user)
    r = _authorize_org_write(user, db.get(Request, request_id))
    if payload.hours is not None and not (1 <= payload.hours <= 24 * 30):
        raise HTTPException(400, "snooze must be between 1 hour and 30 days")
    if payload.hours is None:
        r.snoozed_until = None
        action = "request.unsnoozed"
    else:
        r.snoozed_until = datetime.now(timezone.utc) + timedelta(hours=payload.hours)
        action = "request.snoozed"
    record_audit(
        db, org_id=r.org_id, action=action, resource_type="Request", resource_id=r.id,
        actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"until": r.snoozed_until.isoformat() if r.snoozed_until else None},
    )
    db.commit()
    db.refresh(r)
    return _detail(db, r, user)


@router.post("/requests/{request_id}/resolve", response_model=RequestDetailOut)
def resolve_advice(
    request_id: str, payload: ResolveAdviceIn,
    user: User = Depends(require(Permission.REVIEW_DECIDE)), db: Session = Depends(get_db),
):
    """Approve (or approve-with-edit) the answer to an ADVICE request. Writes
    ``request.approved`` — the same ledger anchor the SLA clock stops on."""
    r = db.get(Request, request_id)
    if r is None or r.org_id != user.org_id:
        raise HTTPException(404, "request not found")
    _, category = _type_info(db, r)
    if category != "ADVICE":
        raise HTTPException(409, "only advice requests are resolved with an answer")
    if r.state in (RequestState.APPROVED, RequestState.CANCELLED):
        raise HTTPException(409, f"request is already {r.state.value.lower()}")
    answer = payload.answer.strip()
    if not answer:
        raise HTTPException(400, "an answer is required")
    edited = bool(r.resolution_draft) and answer != (r.resolution_draft or "").strip()
    r.resolution_note = answer
    r.state = RequestState.APPROVED
    record_audit(
        db, org_id=r.org_id, action="request.approved", resource_type="Request", resource_id=r.id,
        actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"engine": "advice",
                  "draft_used": "edited" if edited else ("as_proposed" if r.resolution_draft else "written_by_human")},
    )
    db.commit()
    db.refresh(r)
    return _detail(db, r, user)


@router.post("/requests/bulk")
def bulk_action(
    payload: BulkActionIn,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    """Bulk queue operations: assign / snooze / unsnooze. Audited per request;
    unknown or foreign ids are skipped and reported, never a partial mystery."""
    from datetime import timedelta

    _require_queue_ops(user)
    if payload.action not in ("assign", "snooze", "unsnooze"):
        raise HTTPException(400, "action must be assign, snooze, or unsnooze")
    if len(payload.ids) == 0 or len(payload.ids) > 100:
        raise HTTPException(400, "between 1 and 100 request ids")
    if payload.action == "assign" and not payload.user_id:
        # mass-unassign must be an explicit intent, not a missing field
        raise HTTPException(400, "assign requires user_id")
    assignee = _validate_assignee(db, user, payload.user_id) if payload.action == "assign" else None
    if payload.action == "snooze" and (payload.hours is None or not (1 <= payload.hours <= 24 * 30)):
        raise HTTPException(400, "snooze hours must be between 1 and 720")

    done, skipped = [], []
    for rid in payload.ids:
        r = db.get(Request, rid)
        if r is None or r.org_id != user.org_id:
            skipped.append(rid)
            continue
        if payload.action == "assign":
            r.assigned_to_user_id = assignee.id if assignee else None
            action = "request.assigned" if assignee else "request.unassigned"
            meta = {"assignee": assignee.name if assignee else None, "bulk": True}
        elif payload.action == "snooze":
            r.snoozed_until = datetime.now(timezone.utc) + timedelta(hours=payload.hours)
            action, meta = "request.snoozed", {"until": r.snoozed_until.isoformat(), "bulk": True}
        else:
            r.snoozed_until = None
            action, meta = "request.unsnoozed", {"bulk": True}
        record_audit(
            db, org_id=r.org_id, action=action, resource_type="Request", resource_id=r.id,
            actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name, metadata=meta,
        )
        done.append(rid)
    db.commit()
    return {"ok": True, "done": done, "skipped": skipped}


@router.get("/requests", response_model=list[RequestSummaryOut])
def list_requests(
    state: str | None = None, lane: str | None = None,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    stmt = select(Request).where(Request.org_id == user.org_id).order_by(Request.created_at.desc())
    try:
        if state:
            stmt = stmt.where(Request.state == RequestState(state))
        if lane:
            stmt = stmt.where(Request.lane == Lane(lane))
    except ValueError:
        raise HTTPException(400, "unknown state or lane filter")
    rows = db.execute(stmt).scalars().all()

    if can(user.role, Permission.REQUEST_READ_ALL):
        pass
    elif can(user.role, Permission.REQUEST_READ_OWN):
        rows = [r for r in rows if _owns(db, user, r)]
    else:
        raise HTTPException(403, "not permitted to list requests")
    return [_summary(db, r) for r in rows]


@router.get("/requests/{request_id}", response_model=RequestDetailOut)
def get_request(request_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = db.get(Request, request_id)
    if r is None:
        raise HTTPException(404, "request not found")
    _authorize_read(db, user, r)
    return _detail(db, r, user)


@router.get("/requests/{request_id}/sla-legs")
def get_sla_legs(request_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The ticket's SLA window partitioned into custody legs from the audit
    ledger — who held the baton when, and which leg the breach fell in."""
    from ..services.sla_legs import build_sla_legs

    r = db.get(Request, request_id)
    if r is None:
        raise HTTPException(404, "request not found")
    _authorize_read(db, user, r)
    return {"ok": True, **build_sla_legs(db, r)}


@router.get("/requests/{request_id}/status", response_model=RequesterStatusOut)
def requester_status(request_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = db.get(Request, request_id)
    if r is None:
        raise HTTPException(404, "request not found")
    _authorize_read(db, user, r)
    cp = db.get(Counterparty, r.counterparty_id)
    type_label, category = _type_info(db, r)

    # ADVICE engine: a 3-stage tracker and the approved answer as the payoff.
    # The requester never learns which engine ran — same page, same shape.
    if category == "ADVICE":
        stages = ["Requested", "With the legal team", "Answered"]
        if r.state == RequestState.APPROVED:
            stage, idx = "Answered", 2
            headline = "Answered — here's what legal says."
            detail = r.resolution_note or ""
        elif r.state == RequestState.CANCELLED:
            stage, idx, headline, detail = "Requested", 0, "Cancelled.", "This request was withdrawn."
        else:
            stage, idx = "With the legal team", 1
            headline = "The legal team is on it."
            detail = f"Filed as: {type_label or 'legal request'}. You'll see the answer here — no need to chase."
        return {
            "ref": r.ref,
            "counterparty_name": type_label or "Legal request",
            "type_label": type_label,
            "nda_type": r.nda_type.value,
            "purpose": (r.details or r.purpose)[:140],
            "stage": stage, "stage_index": idx, "stages": stages,
            "needs_you": False,
            "headline": headline, "detail": detail,
            "document_ready": False,
            "answer": r.resolution_note,
            "expires_at": None,
            "timeline": _timeline(db, r.id),
        }

    label, idx = _STAGE.get(r.state, ("Requested", 0))

    if r.state in (RequestState.IN_REVIEW, RequestState.RETURNED):
        if (r.round or 1) > 1:
            headline = f"Their comments came back — legal is reviewing (round {r.round})."
            detail = "The counterparty proposed changes. Legal is checking them against our playbook before anything goes back out."
        else:
            headline = "Being reviewed by legal — nothing needed from you."
            detail = "A lawyer is checking a couple of terms before it goes out. Typically cleared within a day."
    elif r.state == RequestState.APPROVED:
        headline = "Cleared review — sending to the counterparty."
        detail = "Your NDA is approved and about to be sent for signature."
    elif r.state == RequestState.WITH_COUNTERPARTY:
        headline = f"With {cp.name} for their review" + (f" — round {r.round}." if (r.round or 1) > 1 else ".")
        detail = "They're reading our terms. If they propose changes, legal reviews them here — you don't need to do anything."
    elif r.state == RequestState.OUT_FOR_SIGNATURE:
        headline = f"Sent to {cp.name} for signature."
        detail = "We'll drop the signed copy here as soon as it's countersigned."
    elif r.state in (RequestState.EXECUTED, RequestState.FILED):
        headline = f"Signed by {cp.name} — you're all set."
        if r.expires_at:
            detail = f"The executed NDA is filed. Renewal is tracked — it expires {r.expires_at.strftime('%b %d, %Y')}."
        else:
            detail = "The executed NDA is filed and its renewal date is being tracked."
    else:
        headline = "Your NDA is being drafted."
        detail = "We're assembling it from the approved template. This is usually instant."

    return {
        "ref": r.ref,
        "counterparty_name": cp.name if cp else "—",
        "type_label": type_label,
        "nda_type": r.nda_type.value,
        "purpose": r.purpose,
        "stage": label,
        "stage_index": idx,
        "needs_you": False,
        "headline": headline,
        "detail": detail,
        "document_ready": r.state in (RequestState.EXECUTED, RequestState.FILED),
        "expires_at": r.expires_at.isoformat() if r.expires_at else None,
        "timeline": _timeline(db, r.id),
    }


@router.post("/approvals/steps/{step_id}/approve", response_model=RequestDetailOut)
def approve_step(
    step_id: str, payload: ApproveStepIn,
    user: User = Depends(require(Permission.REVIEW_DECIDE)), db: Session = Depends(get_db),
):
    from ..services.approvals import approval_blockers

    step = db.get(ApprovalStep, step_id)
    if step is None:
        raise HTTPException(404, "approval step not found")
    ladder = step.ladder
    r = _authorize_org_write(user, db.get(Request, ladder.request_id))  # foreign-org step -> 404
    if r.state not in (RequestState.IN_REVIEW, RequestState.RETURNED):
        # a stale step on a matter that already moved on (approved / with the
        # counterparty / signed) must not re-fire the approval anchor
        raise HTTPException(409, f"request is not in review (is {r.state.value})")
    if step.status != StepStatus.PENDING:
        raise HTTPException(409, "step already decided")
    assert_can_clear_rung(user, step.rung)  # rung-gated: seniority enforced

    step.status = StepStatus.APPROVED
    step.decided_by = user.id
    step.decided_at = datetime.now(timezone.utc)
    record_audit(
        db, org_id=r.org_id, action="ladder.step.approved", resource_type="Request", resource_id=r.id,
        actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"rung": step.rung, "reason": step.reason},
    )

    db.refresh(ladder)
    # APPROVED requires BOTH gates: the ladder AND every redline decided —
    # clearing the last step while findings sit PENDING must not flip state
    if all_steps_cleared(ladder):
        ladder.status = "APPROVED"
    if not approval_blockers(db, r):
        from ..services.workflows import mark_stage

        r.state = RequestState.APPROVED
        mark_stage(db, r, "approvals", "done", round_no=r.round)
        record_audit(
            db, org_id=r.org_id, action="request.approved", resource_type="Request", resource_id=r.id,
            actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
            metadata={"steps": len(ladder.steps), "round": r.round},
        )
    db.commit()
    db.refresh(r)
    return _detail(db, r)


@router.post("/requests/{request_id}/send-to-counterparty", response_model=RequestDetailOut)
def send_to_counterparty_route(
    request_id: str,
    user: User = Depends(require(Permission.REQUEST_SEND)), db: Session = Depends(get_db),
):
    """Send the approved paper to the counterparty for THEIR review — the
    negotiation path. Signature is the separate convergence path (/send)."""
    from ..services import intake as intake_svc
    from ..services.negotiation import NegotiationError, send_to_counterparty

    r = _authorize_org_write(user, db.get(Request, request_id))
    if _type_info(db, r)[1] == "ADVICE":
        raise HTTPException(409, "advice requests are resolved with an answer, not negotiated")
    try:
        r = send_to_counterparty(db, r, intake_svc.Actor(user.id, ActorType.USER, user.name))
    except NegotiationError as e:
        raise HTTPException(409, str(e))
    return _detail(db, r, user)


@router.post("/requests/{request_id}/counterparty-return", response_model=RequestDetailOut)
def counterparty_return_route(
    request_id: str, payload: CounterpartyReturnIn,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    """Record the counterparty's returned markup: spins round N+1 — re-redline,
    re-score, rebuilt ladder — on the same ticket."""
    from ..services import intake as intake_svc
    from ..services.negotiation import NegotiationError, record_counterparty_return
    from ..services.playbooks import PlaybookResolutionError

    _require_queue_ops(user)
    r = _authorize_org_write(user, db.get(Request, request_id))
    try:
        r = record_counterparty_return(
            db, r, body_text=payload.body_text,
            actor=intake_svc.Actor(user.id, ActorType.USER, user.name), source="paste",
        )
    except NegotiationError as e:
        raise HTTPException(409, str(e))
    except PlaybookResolutionError as e:
        db.rollback()
        raise HTTPException(409, str(e))
    except IntegrityError:
        # two concurrent returns raced; the unique (request, round) constraint
        # kept the data consistent — surface the loser as a conflict, not a 500
        db.rollback()
        raise HTTPException(409, "a return for this round is already being processed")
    return _detail(db, r, user)


@router.post("/requests/{request_id}/counterparty-return/upload", response_model=RequestDetailOut)
async def counterparty_return_upload_route(
    request_id: str, file: UploadFile = File(...),
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    """Upload variant of the return path (.docx / .pdf / .txt)."""
    from ..services import intake as intake_svc
    from ..services.extract import ExtractionError, extract_text
    from ..services.negotiation import NegotiationError, record_counterparty_return
    from ..services.playbooks import PlaybookResolutionError

    _require_queue_ops(user)
    r = _authorize_org_write(user, db.get(Request, request_id))
    raw = await file.read()
    try:
        body_text = extract_text(file.filename or "upload", raw)
    except ExtractionError as e:
        raise HTTPException(400, str(e))
    try:
        r = record_counterparty_return(
            db, r, body_text=body_text,
            actor=intake_svc.Actor(user.id, ActorType.USER, user.name), source="upload",
        )
    except NegotiationError as e:
        raise HTTPException(409, str(e))
    except PlaybookResolutionError as e:
        db.rollback()
        raise HTTPException(409, str(e))
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "a return for this round is already being processed")
    return _detail(db, r, user)


@router.post("/requests/{request_id}/send", response_model=RequestDetailOut)
def send_request(
    request_id: str,
    user: User = Depends(require(Permission.REQUEST_SEND)), db: Session = Depends(get_db),
):
    r = _authorize_org_write(user, db.get(Request, request_id))
    if r.state != RequestState.APPROVED:
        raise HTTPException(409, f"request must be APPROVED to send (is {r.state.value})")
    if _type_info(db, r)[1] == "ADVICE":
        # a resolved question has nothing to sign — sending would corrupt its
        # state machine (and re-open resolve, double-writing the SLA anchor)
        raise HTTPException(409, "advice requests are resolved with an answer, not sent for signature")
    cp = db.get(Counterparty, r.counterparty_id)
    requester = db.get(Person, r.requester_id)

    # The signing packet. Whenever a review run exists (inbound paper, or ANY
    # request in round >= 2 — the counterparty's markup became the current
    # version), the packet is the counter-proposal WITH the lawyers' decisions
    # applied. Sending the raw current version would transmit clauses a human
    # explicitly rejected.
    from ..services.redline import build_counter_markdown, latest_run

    run = latest_run(db, r.id)
    if run is not None:
        body_md = build_counter_markdown(db, r, run)
        title = f"Counter-proposal — {cp.name if cp else r.ref}"
    else:
        doc = db.get(Document, r.document_id)
        version = db.get(DocumentVersion, doc.current_version_id) if doc else None
        body_md = version.body_markdown if version else ""
        title = doc.title if doc else r.ref

    client = esign.get_esign_client()
    signer_email = settings.esign_signer_email or (requester.email if requester else "signer@example.com")
    try:
        result = client.send_for_signature(
            subject=title, document_html=esign.render_document_html(title, body_md),
            signer_email=signer_email, signer_name=cp.name if cp else "Counterparty",
        )
    except esign.DocuSignError as e:
        raise HTTPException(502, str(e))

    r.esign_envelope_id = result.envelope_id
    r.esign_provider = result.provider
    r.esign_status = result.status
    r.state = RequestState.OUT_FOR_SIGNATURE
    from ..services.workflows import mark_stage as _wf_mark

    _wf_mark(db, r, "approvals", "done", round_no=r.round)
    _wf_mark(db, r, "counterparty", "done", round_no=r.round)  # negotiation converged
    _wf_mark(db, r, "esign", "active", round_no=r.round)
    record_audit(
        db, org_id=r.org_id, action="request.sent", resource_type="Request", resource_id=r.id,
        actor_type=ActorType.SYSTEM, actor_label="System",
        metadata={"envelope_id": result.envelope_id, "provider": result.provider, "signer": signer_email},
    )
    db.commit()
    db.refresh(r)
    return _detail(db, r)


@router.post("/requests/{request_id}/simulate-signature", response_model=RequestDetailOut)
def simulate_signature(
    request_id: str,
    user: User = Depends(require(Permission.REQUEST_SEND)), db: Session = Depends(get_db),
):
    """Stands in for the counterparty countersigning (dev only)."""
    r = _authorize_org_write(user, db.get(Request, request_id))
    if r.state != RequestState.OUT_FOR_SIGNATURE:
        raise HTTPException(409, f"request is not out for signature (is {r.state.value})")
    if r.esign_provider == "docusign":
        raise HTTPException(409, "real DocuSign envelope — completion arrives via /api/esign/webhook")
    cp = db.get(Counterparty, r.counterparty_id)
    r.state = RequestState.EXECUTED
    stamp_execution(r, datetime.now(timezone.utc))  # start the renewal clock
    record_audit(
        db, org_id=r.org_id, action="request.executed", resource_type="Request", resource_id=r.id,
        actor_type=ActorType.SYSTEM, actor_label="E-Sign (stub)",
        metadata={"countersigned_by": cp.name if cp else "counterparty"},
    )
    from ..services.obligations import extract_obligations_for_contract
    from ..services.workflows import mark_stages as _wf_marks

    extract_obligations_for_contract(db, r)  # what the signed contract commits us to
    _wf_marks(db, r, "esign", "obligations", "seal")
    r.state = RequestState.FILED
    record_audit(
        db, org_id=r.org_id, action="request.filed", resource_type="Request", resource_id=r.id,
        actor_type=ActorType.SYSTEM, actor_label="System",
        metadata={"renewal_tracked": True, "expires_in_months": r.term_months,
                  "expires_at": r.expires_at.isoformat() if r.expires_at else None},
    )
    db.commit()
    db.refresh(r)
    return _detail(db, r)

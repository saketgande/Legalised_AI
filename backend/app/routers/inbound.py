"""Inbound third-party review — the counterparty sent their paper.

create(paste) → segment into clauses → run the hybrid engine → proposed changes
(PENDING) → a human approves/edits/rejects each (the governance gate) → when
none are pending the request is APPROVED and the counter-proposal can be sent.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    ActorType,
    Clause,
    Direction,
    Document,
    DocumentVersion,
    NdaType,
    OurRole,
    ProposedChange,
    Request,
    RequestState,
    ReviewRun,
    User,
)
from ..permissions import Permission
from ..schemas import CreateInboundIn, DecideChangeIn, RequestDetailOut
from ..security import assert_can_clear_rung, current_user, require
from ..services.audit import record_audit
from ..services.redline import classify, run_inbound_review, segment
from . import requests as R

router = APIRouter(prefix="/api", tags=["inbound"])


@router.post("/requests/inbound", response_model=RequestDetailOut)
def create_inbound(
    payload: CreateInboundIn,
    user: User = Depends(require(Permission.REQUEST_READ_ALL)),  # inbound review is a legal-staff action
    db: Session = Depends(get_db),
):
    org_id = user.org_id
    requester = R._get_or_create_person(db, org_id, user.name, user.email)
    counterparty = R._get_or_create_counterparty(db, org_id, payload.counterparty_name)

    r = Request(
        ref=R._next_ref(db),
        org_id=org_id,
        type="NDA",
        direction=Direction.INBOUND,
        nda_type=NdaType(payload.nda_type),
        our_role=OurRole.RECIPIENT,
        state=RequestState.NEW,
        requester_id=requester.id,
        counterparty_id=counterparty.id,
        purpose=payload.purpose,
        jurisdiction="US",
        term_months=24,
        channel="EMAIL",
    )
    db.add(r)
    db.flush()
    record_audit(
        db, org_id=org_id, action="request.created", resource_type="Request", resource_id=r.id,
        actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"counterparty": counterparty.name, "direction": "INBOUND", "channel": "EMAIL"},
    )
    record_audit(
        db, org_id=org_id, action="request.classified", resource_type="Request", resource_id=r.id,
        actor_type=ActorType.AGENT, actor_label="Intake Assistant",
        metadata={"direction": "INBOUND", "type": "NDA", "role": "RECIPIENT"},
    )

    # segment the pasted paper into an addressable document
    title = f"{counterparty.name} — inbound NDA (their paper)"
    doc = Document(org_id=org_id, request_id=r.id, origin="UPLOADED", title=title)
    db.add(doc)
    db.flush()
    version = DocumentVersion(
        document_id=doc.id, version_no=1,
        body_markdown=payload.body_text,
        content_hash=hashlib.sha256(payload.body_text.encode("utf-8")).hexdigest(),
        generated_by="counterparty-upload",
    )
    db.add(version)
    db.flush()
    for i, (section_no, heading, body) in enumerate(segment(payload.body_text), start=1):
        db.add(Clause(
            document_version_id=version.id, ordinal=i, section_no=section_no or str(i),
            clause_type=classify(heading, body), heading=heading, body_text=body,
        ))
    doc.current_version_id = version.id
    r.document_id = doc.id
    db.flush()

    # run the hybrid engine
    run = run_inbound_review(db, r)
    r.state = RequestState.IN_REVIEW
    record_audit(
        db, org_id=org_id, action="review.completed", resource_type="Request", resource_id=r.id,
        actor_type=ActorType.AGENT, actor_label="Redline Engine",
        metadata={"summary": run.summary, "proposed_changes": len(run.changes)},
    )
    db.commit()
    db.refresh(r)
    return R._detail(db, r)


@router.post("/changes/{change_id}/decide", response_model=RequestDetailOut)
def decide_change(
    change_id: str, payload: DecideChangeIn,
    user: User = Depends(require(Permission.REVIEW_DECIDE)), db: Session = Depends(get_db),
):
    """approve / edit / reject a single proposed change — the human gate."""
    change = db.get(ProposedChange, change_id)
    if change is None:
        raise HTTPException(404, "proposed change not found")
    action = {"approve": "APPROVED", "reject": "REJECTED", "edit": "APPROVED_WITH_EDIT"}.get(payload.action)
    if action is None:
        raise HTTPException(400, "action must be approve, reject, or edit")
    if action == "APPROVED_WITH_EDIT" and not payload.edited_after_text:
        raise HTTPException(400, "edit requires edited_after_text")
    if change.decision != "PENDING":
        raise HTTPException(409, "change already decided")
    # rung-gated: approving a deviation that needs GC requires GC-rank (rejecting is always allowed)
    if action != "REJECTED":
        assert_can_clear_rung(user, change.triggered_rung)

    run = db.get(ReviewRun, change.run_id)
    r = db.get(Request, run.request_id)

    change.decision = action
    if action == "APPROVED_WITH_EDIT" and payload.edited_after_text is not None:
        change.after_text = payload.edited_after_text
    change.decided_by = user.id
    change.decided_at = datetime.now(timezone.utc)

    record_audit(
        db, org_id=r.org_id,
        action={"APPROVED": "change.approved", "APPROVED_WITH_EDIT": "change.approved_with_edit",
                "REJECTED": "change.rejected"}[action],
        resource_type="Request", resource_id=r.id,
        actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"finding": change.finding, "heading": change.heading, "rule_key": change.rule_key,
                  "rung": change.triggered_rung},
    )

    db.flush()
    db.refresh(run)
    if all(c.decision != "PENDING" for c in run.changes):
        r.state = RequestState.APPROVED
        record_audit(
            db, org_id=r.org_id, action="request.approved", resource_type="Request", resource_id=r.id,
            actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
            metadata={"changes": len(run.changes)},
        )
    db.commit()
    db.refresh(r)
    return R._detail(db, r)

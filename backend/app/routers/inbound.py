"""Inbound third-party review — the counterparty sent their paper.

create(paste) → segment into clauses → run the hybrid engine → proposed changes
(PENDING) → a human approves/edits/rejects each (the governance gate) → when
none are pending the request is APPROVED and the counter-proposal can be sent.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
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
from ..services.extract import extract_text
from ..services.redline import classify, run_inbound_review, segment
from . import requests as R

router = APIRouter(prefix="/api", tags=["inbound"])

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def _ingest_inbound(
    db: Session, user: User, *, counterparty_name: str, nda_type: str, purpose: str,
    body_text: str, source: str,
) -> Request:
    """Attribute an inbound review to the authenticated staff user, then run it
    through the shared intake pipeline."""
    from ..services import intake

    requester = intake.get_or_create_person(db, user.org_id, user.name, user.email)
    return intake.create_inbound(
        db, org=user.org_id, requester=requester,
        actor=intake.Actor(user.id, ActorType.USER, user.name),
        counterparty_name=counterparty_name, nda_type=nda_type, purpose=purpose,
        body_text=body_text, channel="EMAIL", source=source,
    )


@router.post("/requests/inbound", response_model=RequestDetailOut)
def create_inbound(
    payload: CreateInboundIn,
    user: User = Depends(require(Permission.REQUEST_READ_ALL)),  # inbound review is a legal-staff action
    db: Session = Depends(get_db),
):
    r = _ingest_inbound(
        db, user, counterparty_name=payload.counterparty_name, nda_type=payload.nda_type,
        purpose=payload.purpose, body_text=payload.body_text, source="paste",
    )
    return R._detail(db, r)


@router.post("/requests/inbound/upload", response_model=RequestDetailOut)
def create_inbound_upload(
    counterparty_name: str = Form(...),
    nda_type: str = Form("MUTUAL"),
    purpose: str = Form("vendor_evaluation"),
    file: UploadFile = File(...),
    user: User = Depends(require(Permission.REQUEST_READ_ALL)),
    db: Session = Depends(get_db),
):
    content = file.file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(413, "file too large (max 10 MB)")
    body_text = extract_text(file.filename or "", content)  # raises 415 on unsupported type
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    r = _ingest_inbound(
        db, user, counterparty_name=counterparty_name, nda_type=nda_type,
        purpose=purpose, body_text=body_text, source=ext or "file",
    )
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
    if r is None or r.org_id != user.org_id:  # org-scope: no deciding another org's changes
        raise HTTPException(404, "proposed change not found")

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

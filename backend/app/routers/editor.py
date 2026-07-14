"""Drafting Editor endpoint — streaming, playbook-grounded, advisory.

`POST /api/editor/draft` streams an SSE draft/revision: a `grounding` frame
(which playbook positions steered it) → `delta*` (the clause text) → `done`.
The client shows it as an accept/reject suggestion; nothing is auto-applied.

Grounding retrieval (DB) happens up front; the generator only streams model /
assembled text. One `editor.generate` row seals the generation on the chain.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ActorType, User
from ..security import current_user
from ..services import editor as E
from ..services.audit import record_audit

router = APIRouter(prefix="/api/editor", tags=["editor"])


class DraftBody(BaseModel):
    instruction: str
    selection: str | None = None   # the text being revised ("" / null = draft new)


@router.post("/draft")
def draft(body: DraftBody, user: User = Depends(current_user), db: Session = Depends(get_db)):
    instruction = (body.instruction or "").strip()
    if not instruction:
        raise HTTPException(400, "empty instruction")
    selection = body.selection or ""

    grounding = E.retrieve_grounding(db, user, instruction, selection)
    record_audit(
        db, org_id=user.org_id, action="editor.generate",
        resource_type="Organization", resource_id=user.org_id,
        actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"instruction": instruction[:280], "revise": bool(selection.strip()),
                  "grounding": [g.rule_key for g in grounding]},
    )
    grounding_json = E.grounding_payload(grounding)

    def event_stream():
        yield f"data: {json.dumps({'type': 'grounding', 'grounding': grounding_json})}\n\n"
        for delta in E.draft_stream(instruction, selection, grounding):
            if delta:
                yield f"data: {json.dumps({'type': 'delta', 'text': delta})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

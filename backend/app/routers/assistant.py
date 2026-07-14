"""Grounded assistant endpoint — streaming, cited, advisory.

`POST /api/assistant/ask` streams a Server-Sent-Events answer grounded in the
caller's readable workspace. The assistant never mutates state; every query is
sealed on the audit chain (`assistant.query`).

DB work (retrieval + audit) happens up front, while the request-scoped session
is alive; the streaming generator only does model/extract work, so it can't
touch a closed session.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ActorType, Request, User
from ..security import current_user
from ..services import assistant as A
from ..services.audit import record_audit

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class AskBody(BaseModel):
    query: str
    request_id: str | None = None   # optional scope: ground on one request only


def _authorize_scope(db: Session, user: User, request_id: str) -> Request:
    r = db.get(Request, request_id)
    if r is None or r.org_id != user.org_id:
        raise HTTPException(404, "request not found")
    # mirror the read gate used elsewhere; retrieval also re-scopes defensively
    from ..routers.requests import _authorize_read
    _authorize_read(db, user, r)
    return r


@router.post("/ask")
def ask(body: AskBody, user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = (body.query or "").strip()
    if not query:
        raise HTTPException(400, "empty query")
    if body.request_id:
        _authorize_scope(db, user, body.request_id)

    # ── all DB work happens here, before we start streaming ──
    chunks = A.retrieve_context(db, user, query, scope_request_id=body.request_id)
    record_audit(
        db, org_id=user.org_id, action="assistant.query",
        resource_type="Request" if body.request_id else "Organization",
        resource_id=body.request_id or user.org_id,
        actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"query": query[:280], "sources": len(chunks),
                  "scoped": bool(body.request_id)},
    )
    sources = A.sources_payload(chunks)

    def event_stream():
        yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"
        for delta in A.answer_stream(query, chunks):
            if delta:
                yield f"data: {json.dumps({'type': 'delta', 'text': delta})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

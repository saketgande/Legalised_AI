"""Tabular Review endpoints — the document-grid surface.

`GET  /api/tabular/documents` — the reviewable corpus (permission-scoped).
`POST /api/tabular/run`       — SSE stream: `meta` → `cell*` (progressive) → `done`.

All DB work (authorize + fetch every row's clauses) happens up front while the
request session is alive; the streaming generator only runs extraction, so it
never touches a closed session. One `tabular.review` audit row seals the run.
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
from ..services import tabular as T
from ..services.audit import record_audit

router = APIRouter(prefix="/api/tabular", tags=["tabular"])


@router.get("/documents")
def documents(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"rows": T.rows_payload(T.list_documents(db, user))}


class RunBody(BaseModel):
    request_ids: list[str]
    questions: list[str]


@router.post("/run")
def run(body: RunBody, user: User = Depends(current_user), db: Session = Depends(get_db)):
    questions = [q.strip() for q in body.questions if q and q.strip()][:T.MAX_COLS]
    if not body.request_ids or not questions:
        raise HTTPException(400, "select at least one document and one question")

    # ── DB work up front (session alive): authorize rows + fetch their clauses ──
    rows, clauses = T.prepare_rows(db, user, body.request_ids)
    if not rows:
        raise HTTPException(404, "no readable documents in selection")

    record_audit(
        db, org_id=user.org_id, action="tabular.review",
        resource_type="Organization", resource_id=user.org_id,
        actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"documents": len(rows), "questions": len(questions),
                  "cells": len(rows) * len(questions), "columns": questions[:T.MAX_COLS]},
    )

    rows_json = T.rows_payload(rows)

    def event_stream():
        yield f"data: {json.dumps({'type': 'meta', 'rows': rows_json, 'questions': questions})}\n\n"
        for row in rows:
            cl = clauses.get(row.request_id, [])
            for ci, q in enumerate(questions):
                cell = T.extract_cell(q, cl, row.request_id, ci, row.url)
                yield f"data: {json.dumps({'type': 'cell', **T.cell_payload(cell)})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

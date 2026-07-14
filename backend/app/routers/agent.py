"""Agentic workflow endpoint — plan → execute → recommend, streamed.

`POST /api/agent/run` streams an SSE run: `plan` → `step*` (with results) →
`delta*` (the streamed recommendation) → `done`. The agent composes the existing
engines (summary, risk, redline, playbook, workspace search) as read-only tools.

All DB gathering happens up front while the session is alive; the generator only
shapes the in-memory context. One `agent.run` row seals the run on the chain.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ActorType, Request, User
from ..security import current_user
from ..services import agent as AG
from ..services.assistant import retrieve_context, sources_payload
from ..services.audit import record_audit

router = APIRouter(prefix="/api/agent", tags=["agent"])


class RunBody(BaseModel):
    goal: str
    request_id: str | None = None


def _review_context(detail: dict) -> dict | None:
    review = detail.get("review")
    if not review:
        return None
    changes = review.get("changes", [])
    pending = [c for c in changes if c.get("decision") == "PENDING"]
    rung_rank = {"none": 0, "requesting_manager": 3, "vp_legal": 5, "gc": 6}
    top = max(pending, key=lambda c: rung_rank.get(c.get("triggered_rung", "none"), 0), default=None)
    return {
        "pending": len(pending),
        "top": (f"{top.get('heading', '')} — {str(top.get('finding', '')).lower()}" if top else ""),
        "top_rung": (top.get("triggered_rung") if top else None),
    }


@router.post("/run")
def run(body: RunBody, user: User = Depends(current_user), db: Session = Depends(get_db)):
    goal = (body.goal or "").strip()
    if not goal:
        raise HTTPException(400, "empty goal")

    from ..routers.requests import _authorize_read, _detail

    ctx: dict = {"goal": goal, "scope_request_id": None, "scope_ref": None}

    if body.request_id:
        r = db.get(Request, body.request_id)
        if r is None or r.org_id != user.org_id:
            raise HTTPException(404, "request not found")
        _authorize_read(db, user, r)
        detail = _detail(db, r, user)
        ctx.update({
            "scope_request_id": r.id,
            "scope_ref": r.ref,
            "clauses": (detail.get("document") or {}).get("clauses", []) if detail.get("document") else [],
            "risk": detail.get("risk"),
            "review": _review_context(detail),
        })
    else:
        hits = retrieve_context(db, user, goal, scope_request_id=None)
        ctx["search_hits"] = sources_payload(hits)

    steps = AG.plan(goal, scoped=bool(body.request_id))

    record_audit(
        db, org_id=user.org_id, action="agent.run",
        resource_type="Request" if body.request_id else "Organization",
        resource_id=body.request_id or user.org_id,
        actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"goal": goal[:280], "scoped": bool(body.request_id),
                  "steps": [s.key for s in steps]},
    )

    def event_stream():
        yield from AG.run_steps(goal, ctx, steps)

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

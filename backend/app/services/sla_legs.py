"""Multi-leg SLA — one window, partitioned into custody legs.

Ported from the legal_intake intake module (`modules/intake/src/sla/legs.ts`).
The idea: a ticket's single SLA window is split into custody legs by the
hand-off ledger — who held the baton when. A hand-off can no longer hide a
breach: the breach instant lands inside exactly one leg, and every leg reports
the share of the SLA window it consumed. "One window, no resets."

Frontdoor has no separate hand-off table — but the hash-chained AuditEvent
ledger already records every custody change, so the legs derive from it:

    actor_type AGENT  -> the AI agent holds it     ("agent")
    actor_type USER   -> a human holds it          ("human", named)
    actor_type SYSTEM -> parked / routing          ("queue")

Deliberately evidence-not-policy: legs carry elapsed time and window-share,
not per-leg budgets.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ActorType, AuditEvent, Lane, Request, RequestState

# lane SLA defaults — mirrors services/metrics.TARGET_HOURS
_TARGET_HOURS = {"AUTO": 8, "ASSISTED": 24, "ESCALATED": 48}
_DEFAULT_TARGET = 24

# audit actions that mean "legal is done" — the clock stops here (metrics parity)
_RESOLVED_STATES = {
    RequestState.APPROVED, RequestState.WITH_COUNTERPARTY,
    RequestState.OUT_FOR_SIGNATURE, RequestState.EXECUTED, RequestState.FILED,
}
_TERMINAL_ACTIONS = ("request.approved", "request.auto_approved", "request.filed",
                     "request.executed", "request.closed")


def _target_hours(r: Request) -> int:
    if r.sla_target_hours:
        return r.sla_target_hours
    if r.lane is not None:
        return _TARGET_HOURS.get(r.lane.value, _DEFAULT_TARGET)
    return _DEFAULT_TARGET


def _ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _holder_for(actor_type: ActorType) -> str:
    if actor_type == ActorType.AGENT:
        return "agent"
    if actor_type == ActorType.USER:
        return "human"
    return "queue"


def _label_for(holder: str, user_name: str | None) -> str:
    if holder == "agent":
        return "AI agent"
    if holder == "human":
        return user_name or "Assignee"
    return "Intake queue"


@dataclass
class _Seg:
    holder: str
    holder_label: str
    holder_user_id: str | None
    start_ts: int
    end_ts: int


def build_sla_legs(db: Session, request: Request) -> dict:
    """The ticket's SLA window as an ordered list of custody legs, built from
    the audit ledger. Same shape as the legal_intake SlaLegsDTO."""
    events = db.execute(
        select(AuditEvent)
        .where(AuditEvent.resource_id == request.id, AuditEvent.resource_type == "Request")
        .order_by(AuditEvent.chain_position.asc())
    ).scalars().all()

    submitted_ts = _ms(request.created_at)
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    sla_hours = _target_hours(request)
    sla_ms = max(sla_hours, 0) * 3600 * 1000
    breach_ts = submitted_ts + sla_ms

    # closed = the first terminal audit action (clock stops there); else open
    closed_ts: int | None = None
    if request.state in (RequestState.FILED, RequestState.EXECUTED, RequestState.CANCELLED) \
            or (request.state == RequestState.APPROVED):
        for e in events:
            if e.action in _TERMINAL_ACTIONS:
                closed_ts = _ms(e.created_at)
                break

    end_of_life = max(closed_ts if closed_ts is not None else now, submitted_ts)

    # derive baton-passes: a pass happens each time the holder changes.
    passes: list[tuple[str, str | None, str | None, int]] = []  # (holder, user_id, user_name, at_ts)
    for e in events:
        holder = _holder_for(e.actor_type)
        user_id = e.actor_id if holder == "human" else None
        user_name = e.actor_label if holder == "human" else None
        at = min(max(_ms(e.created_at), submitted_ts), end_of_life)
        if passes and passes[-1][0] == holder and passes[-1][1] == user_id:
            continue  # same holder — not a hand-off
        passes.append((holder, user_id, user_name, at))

    # walk passes into segments (initial cursor = queue at submission)
    segs: list[_Seg] = []
    cur_holder, cur_uid, cur_label, cur_start = "queue", None, _label_for("queue", None), submitted_ts
    for holder, uid, uname, at in passes:
        if at > cur_start:
            segs.append(_Seg(cur_holder, cur_label, cur_uid, cur_start, at))
            cur_start = at
        cur_holder, cur_uid, cur_label = holder, uid, _label_for(holder, uname)
    segs.append(_Seg(cur_holder, cur_label, cur_uid, cur_start, end_of_life))

    legs = []
    for i, s in enumerate(segs):
        elapsed = s.end_ts - s.start_ts
        legs.append({
            "holder": s.holder,
            "holder_user_id": s.holder_user_id,
            "holder_label": s.holder_label,
            "start_ts": s.start_ts,
            "end_ts": s.end_ts,
            "elapsed_ms": elapsed,
            "pct_of_sla": round(elapsed / sla_ms * 100) if sla_ms > 0 else 0,
            "active": closed_ts is None and i == len(segs) - 1,
            "breached_during_leg": sla_ms > 0 and s.start_ts <= breach_ts < s.end_ts,
        })

    return {
        "legs": legs,
        "sla_ms": sla_ms,
        "sla_hours": sla_hours,
        "breach_ts": breach_ts,
        "total_elapsed_ms": end_of_life - submitted_ts,
        "breached": sla_ms > 0 and end_of_life >= breach_ts,
        "closed": closed_ts is not None,
        "submitted_ts": submitted_ts,
    }

"""Operations metrics — SLA compliance, deflection, turnaround.

The value story is speed: NDAs handled fast, most without a lawyer. This computes
the numbers a legal-ops buyer actually tracks (CLOC KPIs): deflection rate,
SLA compliance, cycle time, and per-request SLA posture.

SLA clock starts at ``created_at``. It stops the moment legal's work is done —
when the request first reaches a RESOLVED state (APPROVED, or auto-approved). That
timestamp comes from the immutable audit ledger (the ``request.approved`` /
``request.auto_approved`` event), NOT from ``Request.updated_at``: ``updated_at``
keeps advancing on every downstream mutation (sent → out-for-signature → executed
→ filed), so anchoring the clock to it would count the counterparty's countersign
delay against legal and flip a 5-hour approval into a multi-day "miss". Cancelled
requests are excluded.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import AuditEvent, Counterparty, Lane, Person, Request, RequestState

# audit actions that mark the moment a request first became "legal is done"
RESOLUTION_ACTIONS = ("request.approved", "request.auto_approved")

# turnaround targets in hours, by triage lane (AUTO should be ~instant; escalations get longer)
TARGET_HOURS = {"AUTO": 8, "ASSISTED": 24, "ESCALATED": 48}
DEFAULT_TARGET = 24  # inbound reviews / unlaned requests

# "legal is done" — the SLA clock stops here
RESOLVED_STATES = {
    RequestState.APPROVED, RequestState.OUT_FOR_SIGNATURE,
    RequestState.EXECUTED, RequestState.FILED,
}


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _target(lane: Lane | None) -> int:
    return TARGET_HOURS.get(lane.value, DEFAULT_TARGET) if lane else DEFAULT_TARGET


def _target_for(r: Request) -> int:
    """Per-request override (request-type default or routing-rule action) wins;
    otherwise the lane default."""
    return r.sla_target_hours if r.sla_target_hours else _target(r.lane)


def _workflow_insights(db: Session, org_id: str, reqs: list[Request]) -> dict:
    """Where the clock goes (by rung kind, from instance timings), autonomy
    (rungs completed without a human), and per-type override rate (how often a
    lawyer edits/rejects what the engine proposed — the template-health metric)."""
    from ..models import ProposedChange, ReviewRun

    clock = {"D": 0, "A": 0, "H": 0, "T": 0}
    rungs_done = rungs_auto = 0
    for r in reqs:
        for rung in (r.workflow_rungs or []):
            kind = rung.get("kind")
            if kind in clock:
                clock[kind] += int(rung.get("spent_seconds") or 0)
            if rung.get("status") == "done":
                rungs_done += 1
                if kind in ("D", "A"):
                    rungs_auto += 1

    # override rate per contract type: decisions where the human changed the
    # engine's proposal (edited or rejected) / all decided proposals
    per_type: dict[str, dict[str, int]] = {}
    run_rows = db.execute(
        select(ReviewRun.id, Request.type).join(Request, ReviewRun.request_id == Request.id)
        .where(Request.org_id == org_id)
    ).all()
    type_by_run = {rid: (t or "nda").lower() for rid, t in run_rows}
    if type_by_run:
        for run_id, decision in db.execute(
            select(ProposedChange.run_id, ProposedChange.decision)
            .where(ProposedChange.run_id.in_(list(type_by_run.keys())),
                   ProposedChange.decision != "PENDING")
        ).all():
            t = type_by_run.get(run_id, "nda")
            bucket = per_type.setdefault(t, {"decided": 0, "overridden": 0})
            bucket["decided"] += 1
            if decision in ("APPROVED_WITH_EDIT", "REJECTED"):
                bucket["overridden"] += 1

    return {
        "clock_seconds": clock,
        "autonomy_rate": (rungs_auto / rungs_done) if rungs_done else None,
        "override_rates": {
            t: {"rate": (b["overridden"] / b["decided"]) if b["decided"] else None,
                "decided": b["decided"]}
            for t, b in sorted(per_type.items())
        },
    }


def ops_metrics(db: Session, org_id: str) -> dict:
    now = datetime.now(timezone.utc)
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # exclude pre-platform seeded contracts (channel="SEED") — they never went through
    # intake, so counting them would report fictional instant auto-resolves.
    reqs = db.execute(
        select(Request).where(Request.org_id == org_id, Request.channel != "SEED")
    ).scalars().all()

    # Resolution timestamp per request = earliest approval event in the append-only
    # audit ledger. Immutable, so (unlike updated_at) it never drifts as the request
    # moves on to signature/filing. One grouped query for the whole org.
    resolved_at: dict[str, datetime] = {
        rid: _aware(ts)
        for rid, ts in db.execute(
            select(AuditEvent.resource_id, func.min(AuditEvent.created_at))
            .where(
                AuditEvent.org_id == org_id,
                AuditEvent.resource_type == "Request",
                AuditEvent.action.in_(RESOLUTION_ACTIONS),
            )
            .group_by(AuditEvent.resource_id)
        ).all()
    }

    total = len(reqs)
    auto = resolved = cancelled = in_flight = 0
    breached = at_risk = on_track = 0
    met = missed = 0
    cycle_sum = 0.0
    cycle_n = 0
    vol = [0] * 7
    rows: list[dict] = []

    for r in reqs:
        created = _aware(r.created_at)
        # fall back to updated_at only if the ledger has no approval event (legacy rows)
        resolution = resolved_at.get(r.id) or _aware(r.updated_at or r.created_at)
        target = _target_for(r)
        if r.lane == Lane.AUTO:
            auto += 1

        d0 = created.replace(hour=0, minute=0, second=0, microsecond=0)
        idx = 6 - int((today0 - d0).total_seconds() // 86400)
        if 0 <= idx < 7:
            vol[idx] += 1

        status = None
        elapsed = cyc = None
        if r.state == RequestState.CANCELLED:
            cancelled += 1
            status = "cancelled"
        elif r.state in RESOLVED_STATES:
            resolved += 1
            cyc = max(0.0, (resolution - created).total_seconds() / 3600)
            cycle_sum += cyc
            cycle_n += 1
            if cyc <= target:
                met += 1; status = "met"
            else:
                missed += 1; status = "missed"
        else:
            in_flight += 1
            elapsed = max(0.0, (now - created).total_seconds() / 3600)
            if elapsed > target:
                breached += 1; status = "breached"
            elif elapsed > 0.75 * target:
                at_risk += 1; status = "at_risk"
            else:
                on_track += 1; status = "on_track"

        cp = db.get(Counterparty, r.counterparty_id)
        pr = db.get(Person, r.requester_id)
        rows.append({
            "id": r.id, "ref": r.ref,
            "counterparty": cp.name if cp else "—",
            "requester": pr.name if pr else "—",
            "lane": r.lane.value if r.lane else None,
            "direction": r.direction.value,
            "state": r.state.value,
            "target_hours": target,
            "elapsed_hours": round(elapsed, 2) if elapsed is not None else None,
            "cycle_hours": round(cyc, 2) if cyc is not None else None,
            "status": status,
        })

    order = {"breached": 0, "at_risk": 1, "on_track": 2, "missed": 3, "met": 4, "cancelled": 5}
    rows.sort(key=lambda x: (order.get(x["status"], 9), -((x["elapsed_hours"] or 0))))

    workflow = _workflow_insights(db, org_id, reqs)

    return {
        "workflow": workflow,
        "totals": {"total": total, "in_flight": in_flight, "resolved": resolved,
                   "auto_resolved": auto, "cancelled": cancelled},
        "deflection_rate": (auto / total) if total else 0.0,
        "sla": {
            "breached": breached, "at_risk": at_risk, "on_track": on_track,
            "compliance_rate": (met / (met + missed)) if (met + missed) else None,
            "avg_cycle_hours": round(cycle_sum / cycle_n, 1) if cycle_n else None,
        },
        "targets": {**TARGET_HOURS, "default": DEFAULT_TARGET},
        "volume_7d": vol,
        "rows": rows,
    }

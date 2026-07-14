"""Contract lifecycle — the CLM half.

Once an NDA is executed and filed it stops being a request and becomes a tracked
contract: its expiry is derived from the executed date plus the negotiated term,
surfaced in a registry with renewal posture (active / expiring soon / expired /
renewed), and renewable into a fresh request in one click.

This is what turns "its renewal date is being tracked" from copy into a feature:
the request → classify → draft → approve → sign → **file → track → renew** loop,
closed.
"""
from __future__ import annotations

import calendar
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ActorType, Counterparty, Person, Request, RequestState
from .audit import record_audit

# a contract counts as "expiring soon" when it lapses within this many days
EXPIRING_SOON_DAYS = 90
# states in which a request is an executed, filed contract
FILED_STATES = {RequestState.EXECUTED, RequestState.FILED}


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def add_months(dt: datetime, months: int) -> datetime:
    """Add whole months, clamping the day to the end of the target month
    (so 31 Jan + 1 month = 28/29 Feb, not an invalid date)."""
    m = dt.month - 1 + months
    year = dt.year + m // 12
    month = m % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def stamp_execution(r: Request, when: datetime) -> None:
    """Record the contract's executed + expiry timestamps at the moment of
    execution. Idempotent — never overwrites an existing executed_at, so a
    duplicate provider event or a re-run can't move the clock."""
    if r.executed_at is None:
        r.executed_at = when
        r.expires_at = add_months(when, r.term_months or 24)


def _status(days_left: int | None, renewed: bool) -> str:
    if renewed:
        return "renewed"
    if days_left is None:
        return "active"  # unknown expiry — treat as active rather than alarming
    if days_left < 0:
        return "expired"
    if days_left <= EXPIRING_SOON_DAYS:
        return "expiring"
    return "active"


def contract_registry(db: Session, org_id: str) -> dict:
    now = datetime.now(timezone.utc)
    contracts = db.execute(
        select(Request).where(Request.org_id == org_id, Request.state.in_(FILED_STATES))
    ).scalars().all()

    # contracts that have already been renewed (some other request points back at them)
    renewed_ids = set(
        db.execute(
            select(Request.renewed_from_id).where(
                Request.org_id == org_id, Request.renewed_from_id.is_not(None)
            )
        ).scalars().all()
    )

    counts = {"active": 0, "expiring": 0, "expired": 0, "renewed": 0}
    rows: list[dict] = []
    for r in contracts:
        exp = _aware(r.expires_at) if r.expires_at else None
        exec_ = _aware(r.executed_at) if r.executed_at else None
        days_left = int((exp - now).total_seconds() // 86400) if exp else None
        status = _status(days_left, r.id in renewed_ids)
        counts[status] += 1
        cp = db.get(Counterparty, r.counterparty_id)
        rows.append({
            "id": r.id,
            "ref": r.ref,
            "counterparty": cp.name if cp else "—",
            "nda_type": r.nda_type.value,
            "direction": r.direction.value,
            "term_months": r.term_months,
            "executed_at": exec_.isoformat() if exec_ else None,
            "expires_at": exp.isoformat() if exp else None,
            "days_left": days_left,
            "status": status,
        })

    # soonest-to-lapse first; renewed/active with far expiry sink to the bottom
    order = {"expired": 0, "expiring": 1, "active": 2, "renewed": 3}
    rows.sort(key=lambda x: (order.get(x["status"], 9),
                             x["days_left"] if x["days_left"] is not None else 10 ** 9))

    return {
        "totals": {"total": len(contracts), **counts},
        "expiring_soon_days": EXPIRING_SOON_DAYS,
        "rows": rows,
    }


class ContractError(Exception):
    """Renewal precondition failed (not found / not executed)."""


def start_renewal(db: Session, org_id: str, contract_id: str, *, actor_id: str, actor_name: str) -> Request:
    """Spin up a fresh outbound request that renews an executed contract, carrying
    the same counterparty / purpose / term forward and linking back to the original.
    Runs through the standard intake pipeline, so the renewal is triaged, drafted,
    and auto/assisted-routed exactly like any new NDA."""
    from .intake import Actor, create_outbound

    orig = db.get(Request, contract_id)
    if orig is None or orig.org_id != org_id:
        raise ContractError("contract not found")
    if orig.state not in FILED_STATES:
        raise ContractError("only executed contracts can be renewed")

    # idempotent: if a renewal already exists, return it rather than spawning a duplicate
    existing = db.execute(
        select(Request).where(Request.renewed_from_id == contract_id)
    ).scalars().first()
    if existing is not None:
        return existing

    requester = db.get(Person, orig.requester_id)
    counterparty = db.get(Counterparty, orig.counterparty_id)
    renewal = create_outbound(
        db, org=org_id, requester=requester,
        actor=Actor(id=actor_id, type=ActorType.USER, label=actor_name),
        counterparty_name=counterparty.name if counterparty else "Counterparty",
        nda_type=orig.nda_type.value, purpose=orig.purpose, jurisdiction=orig.jurisdiction,
        term_months=orig.term_months, channel="RENEWAL", playbook_id=orig.playbook_id,
    )
    renewal.renewed_from_id = orig.id
    record_audit(
        db, org_id=org_id, action="contract.renewal_started", resource_type="Request",
        resource_id=orig.id, actor_id=actor_id, actor_type=ActorType.USER, actor_label=actor_name,
        metadata={"renewal_ref": renewal.ref, "renewal_id": renewal.id, "counterparty": counterparty.name if counterparty else None},
    )
    db.commit()
    db.refresh(renewal)
    return renewal

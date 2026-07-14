"""Post-signature obligations — what the executed contract commits us to.

Extraction is DETERMINISTIC, from the contract's structured clauses + facts:
dates and durations are exactly what LLMs get wrong, so the renewal clock,
survival window, and return/destruction duty are derived from the term and the
clause types actually present in the executed document. (A future LLM pass can
propose prose obligations as governed PENDING decisions; it never writes rows
directly.)

Idempotent per contract: extraction runs once at execution; re-running skips
contracts that already have rows.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import (
    ActorType, Clause, Document, DocumentVersion, Obligation, ObligationKind,
    ObligationStatus, Request,
)
from .audit import record_audit
from .contracts import add_months


def _clause_types_of(db: Session, r: Request) -> set[str]:
    if not r.document_id:
        return set()
    doc = db.get(Document, r.document_id)
    if doc is None or not doc.current_version_id:
        return set()
    version = db.get(DocumentVersion, doc.current_version_id)
    clauses = db.execute(
        select(Clause).where(Clause.document_version_id == version.id)
    ).scalars().all()
    return {c.clause_type for c in clauses if c.clause_type}


def extract_obligations_for_contract(db: Session, r: Request) -> list[Obligation]:
    """Create the contract's obligation rows at execution. Idempotent twice over:
    the read-guard covers the common case, and the (request_id, kind) unique
    index arbitrates concurrent callers — the loser rolls back and yields."""
    existing = db.execute(
        select(Obligation.id).where(Obligation.request_id == r.id)
    ).first()
    if existing is not None or r.executed_at is None:
        return []

    ctypes = _clause_types_of(db, r)
    term = r.term_months or 24
    obligations: list[Obligation] = [
        # the renewal decision always exists once a contract has an expiry
        Obligation(
            org_id=r.org_id, request_id=r.id, kind=ObligationKind.RENEWAL,
            description=f"Renew or let lapse — the {term}-month term ends.",
            due_at=r.expires_at, source="contract-facts",
        ),
    ]
    if "term" in ctypes:
        obligations.append(Obligation(
            org_id=r.org_id, request_id=r.id, kind=ObligationKind.SURVIVAL,
            description=(f"Confidentiality obligations survive {term} months after "
                         "disclosure — treat received information as confidential until then."),
            due_at=add_months(r.expires_at, term) if r.expires_at else None,
            source="TRM",
        ))
    if "return_destruction" in ctypes:
        obligations.append(Obligation(
            org_id=r.org_id, request_id=r.id, kind=ObligationKind.RETURN_DESTRUCTION,
            description="On request or termination: return or destroy their confidential "
                        "information and certify destruction in writing.",
            due_at=None,  # on-demand duty, no fixed date
            source="RET",
        ))
    # Savepoint so a lost race only rolls back the obligation insert — never the
    # caller's pending state changes (e.g. the EXECUTED transition on the request).
    try:
        with db.begin_nested():
            db.add_all(obligations)
            db.flush()
    except IntegrityError:
        return []  # a concurrent caller won the race — yield to its rows
    for o in obligations:
        record_audit(
            db, org_id=r.org_id, action="obligation.created", resource_type="Obligation",
            resource_id=o.id, actor_type=ActorType.SYSTEM, actor_label="CLM Engine",
            metadata={"request_ref": r.ref, "kind": o.kind.value,
                      "due_at": o.due_at.isoformat() if o.due_at else None},
        )
    return obligations


def list_obligations(db: Session, org_id: str, request_id: str) -> list[dict]:
    rows = db.execute(
        select(Obligation)
        .where(Obligation.org_id == org_id, Obligation.request_id == request_id)
        .order_by(Obligation.due_at.asc().nulls_last(), Obligation.created_at.asc())
    ).scalars().all()
    now = datetime.now(timezone.utc)
    out = []
    for o in rows:
        due = o.due_at
        overdue = bool(due and o.status == ObligationStatus.OPEN and due < now)
        out.append({
            "id": o.id, "kind": o.kind.value, "description": o.description,
            "due_at": due.isoformat() if due else None, "status": o.status.value,
            "overdue": overdue, "source": o.source,
            "resolved_by": o.resolved_by,
            "resolved_at": o.resolved_at.isoformat() if o.resolved_at else None,
        })
    return out


class ObligationError(Exception):
    pass


def resolve_obligation(db: Session, org_id: str, obligation_id: str, *, done: bool,
                       actor_id: str, actor_name: str) -> Obligation:
    o = db.get(Obligation, obligation_id)
    if o is None or o.org_id != org_id:
        raise ObligationError("obligation not found")
    if o.status != ObligationStatus.OPEN:
        return o  # idempotent — already resolved
    o.status = ObligationStatus.DONE if done else ObligationStatus.WAIVED
    o.resolved_by = actor_name
    o.resolved_at = datetime.now(timezone.utc)
    record_audit(
        db, org_id=org_id,
        action="obligation.completed" if done else "obligation.waived",
        resource_type="Obligation", resource_id=o.id,
        actor_id=actor_id, actor_type=ActorType.USER, actor_label=actor_name,
        metadata={"kind": o.kind.value, "description": o.description[:120]},
    )
    return o

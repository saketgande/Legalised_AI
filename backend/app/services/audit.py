"""Append-only, hash-chained audit log.

Every state-changing path calls ``record_audit``. The chain is per-organisation:
each row's ``content_hash`` folds in the previous row's hash and a monotonic
``chain_position``, so a later tamper is detectable by re-walking the chain
(``verify_chain``). This is the evidentiary backbone — in a legal product the
audit row is the anchor, so we never UPDATE or DELETE one; corrections are new
rows.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ActorType, AuditEvent

GENESIS = "0" * 64


def _canonical(
    *,
    chain_position: int,
    prev_hash: str,
    action: str,
    resource_type: str,
    resource_id: str,
    actor_id: str | None,
    actor_type: str,
    metadata: dict,
) -> str:
    payload = {
        "chain_position": chain_position,
        "prev_hash": prev_hash,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "actor_id": actor_id,
        "actor_type": actor_type,
        "metadata": metadata,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record_audit(
    db: Session,
    *,
    org_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    actor_id: str | None = None,
    actor_type: ActorType = ActorType.SYSTEM,
    actor_label: str = "System",
    metadata: dict | None = None,
) -> AuditEvent:
    metadata = metadata or {}
    last = db.execute(
        select(AuditEvent)
        .where(AuditEvent.org_id == org_id)
        .order_by(AuditEvent.chain_position.desc())
        .limit(1)
    ).scalar_one_or_none()

    position = 1 if last is None else last.chain_position + 1
    prev_hash = GENESIS if last is None else last.content_hash

    canonical = _canonical(
        chain_position=position,
        prev_hash=prev_hash,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_id=actor_id,
        actor_type=actor_type.value,
        metadata=metadata,
    )
    content_hash = _hash(canonical)

    event = AuditEvent(
        org_id=org_id,
        chain_position=position,
        prev_hash=prev_hash,
        content_hash=content_hash,
        actor_id=actor_id,
        actor_type=actor_type,
        actor_label=actor_label,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        metadata_json=metadata,
    )
    db.add(event)
    db.flush()
    return event


def verify_chain(db: Session, org_id: str) -> dict:
    """Re-walk the chain; report the first break (if any)."""
    rows = db.execute(
        select(AuditEvent)
        .where(AuditEvent.org_id == org_id)
        .order_by(AuditEvent.chain_position.asc())
    ).scalars().all()

    prev = GENESIS
    for i, row in enumerate(rows, start=1):
        if row.chain_position != i or row.prev_hash != prev:
            return {"intact": False, "broken_at": row.chain_position, "count": len(rows)}
        recomputed = _hash(
            _canonical(
                chain_position=row.chain_position,
                prev_hash=row.prev_hash,
                action=row.action,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                actor_id=row.actor_id,
                actor_type=row.actor_type.value,
                metadata=row.metadata_json,
            )
        )
        if recomputed != row.content_hash:
            return {"intact": False, "broken_at": row.chain_position, "count": len(rows)}
        prev = row.content_hash
    return {"intact": True, "broken_at": None, "count": len(rows)}

"""Read-only surfaces: the playbook and the audit-chain health badge."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Organization, Playbook, PlaybookRule
from ..services.audit import verify_chain

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/playbook/rules")
def list_rules(db: Session = Depends(get_db)):
    playbook = db.execute(
        select(Playbook).where(Playbook.active == True)  # noqa: E712
    ).scalars().first()
    if playbook is None:
        return {"playbook": None, "rules": []}
    rules = db.execute(
        select(PlaybookRule)
        .where(PlaybookRule.playbook_id == playbook.id)
        .order_by(PlaybookRule.ordinal.asc())
    ).scalars().all()
    return {
        "playbook": {"id": playbook.id, "name": playbook.name, "version": playbook.version},
        "rules": [
            {
                "rule_key": r.rule_key,
                "clause_type": r.clause_type,
                "heading": r.heading,
                "preferred_position": r.preferred_position,
                "mandatory": r.mandatory,
                "deviation_rung": r.deviation_rung,
                "rationale": r.rationale,
            }
            for r in rules
        ],
    }


@router.get("/audit/verify")
def audit_verify(db: Session = Depends(get_db)):
    org = db.execute(select(Organization)).scalars().first()
    if org is None:
        return {"intact": True, "broken_at": None, "count": 0}
    return verify_chain(db, org.id)

"""Playbook administration — CRUD the clause rules the engine reasons against.

Gated on PLAYBOOK_MANAGE (admin / GC / legal-ops). Every mutation bumps the
playbook version and writes a chain-sealed audit row, because "what was our
standard position on that date" is itself a legal question.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ActorType, Playbook, PlaybookRule, ProposedChange, User
from ..permissions import RUNG_RANK, Permission
from ..security import require
from ..services.audit import record_audit

router = APIRouter(prefix="/api/admin/playbook", tags=["playbook-admin"])

_VALID_RUNGS = set(RUNG_RANK.keys())


class RuleIn(BaseModel):
    rule_key: str
    clause_type: str
    heading: str
    ordinal: int = 0
    preferred_position: str = ""
    preferred_body: str
    rationale: str = ""
    mandatory: bool = True
    deviation_rung: str = "none"
    nda_type: str | None = None  # applies_when.ndaType: MUTUAL | ONE_WAY | null(any)


def _active_playbook(db: Session, org_id: str) -> Playbook:
    pb = db.execute(
        select(Playbook).where(Playbook.org_id == org_id, Playbook.active == True)  # noqa: E712
    ).scalars().first()
    if pb is None:
        raise HTTPException(404, "no active playbook for organisation")
    return pb


def _rule_out(r: PlaybookRule) -> dict:
    return {
        "id": r.id, "rule_key": r.rule_key, "clause_type": r.clause_type, "heading": r.heading,
        "ordinal": r.ordinal, "preferred_position": r.preferred_position, "preferred_body": r.preferred_body,
        "rationale": r.rationale, "mandatory": r.mandatory, "deviation_rung": r.deviation_rung,
        "nda_type": (r.applies_when or {}).get("ndaType"),
    }


def _validate(payload: RuleIn) -> None:
    if payload.deviation_rung not in _VALID_RUNGS:
        raise HTTPException(400, f"deviation_rung must be one of {sorted(_VALID_RUNGS)}")
    if payload.nda_type not in (None, "MUTUAL", "ONE_WAY"):
        raise HTTPException(400, "nda_type must be MUTUAL, ONE_WAY, or null")
    if not payload.rule_key.strip() or not payload.heading.strip():
        raise HTTPException(400, "rule_key and heading are required")


def _bump_version(db: Session, pb: Playbook) -> None:
    pb.version = (pb.version or 1) + 1


@router.get("")
def get_playbook(user: User = Depends(require(Permission.PLAYBOOK_MANAGE)), db: Session = Depends(get_db)):
    pb = _active_playbook(db, user.org_id)
    rules = db.execute(
        select(PlaybookRule).where(PlaybookRule.playbook_id == pb.id).order_by(PlaybookRule.ordinal.asc())
    ).scalars().all()
    return {"playbook": {"id": pb.id, "name": pb.name, "version": pb.version}, "rules": [_rule_out(r) for r in rules]}


@router.post("/rules")
def create_rule(payload: RuleIn, user: User = Depends(require(Permission.PLAYBOOK_MANAGE)), db: Session = Depends(get_db)):
    _validate(payload)
    pb = _active_playbook(db, user.org_id)
    dupe = db.execute(
        select(PlaybookRule).where(PlaybookRule.playbook_id == pb.id, PlaybookRule.rule_key == payload.rule_key.strip())
    ).scalars().first()
    if dupe:
        raise HTTPException(409, f"rule_key '{payload.rule_key}' already exists")
    r = PlaybookRule(
        playbook_id=pb.id, rule_key=payload.rule_key.strip(), clause_type=payload.clause_type.strip(),
        heading=payload.heading.strip(), ordinal=payload.ordinal,
        preferred_position=payload.preferred_position, preferred_body=payload.preferred_body,
        rationale=payload.rationale, mandatory=payload.mandatory, deviation_rung=payload.deviation_rung,
        applies_when={"ndaType": payload.nda_type} if payload.nda_type else {}, structured_params={},
    )
    db.add(r)
    _bump_version(db, pb)
    db.flush()
    record_audit(
        db, org_id=user.org_id, action="playbook.rule.created", resource_type="PlaybookRule", resource_id=r.id,
        actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"rule_key": r.rule_key, "heading": r.heading, "playbook_version": pb.version},
    )
    db.commit()
    return _rule_out(r)


@router.put("/rules/{rule_id}")
def update_rule(rule_id: str, payload: RuleIn, user: User = Depends(require(Permission.PLAYBOOK_MANAGE)), db: Session = Depends(get_db)):
    _validate(payload)
    pb = _active_playbook(db, user.org_id)
    r = db.get(PlaybookRule, rule_id)
    if r is None or r.playbook_id != pb.id:
        raise HTTPException(404, "rule not found")
    before = _rule_out(r)
    r.rule_key = payload.rule_key.strip()
    r.clause_type = payload.clause_type.strip()
    r.heading = payload.heading.strip()
    r.ordinal = payload.ordinal
    r.preferred_position = payload.preferred_position
    r.preferred_body = payload.preferred_body
    r.rationale = payload.rationale
    r.mandatory = payload.mandatory
    r.deviation_rung = payload.deviation_rung
    r.applies_when = {"ndaType": payload.nda_type} if payload.nda_type else {}
    _bump_version(db, pb)
    db.flush()
    record_audit(
        db, org_id=user.org_id, action="playbook.rule.updated", resource_type="PlaybookRule", resource_id=r.id,
        actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"rule_key": r.rule_key, "playbook_version": pb.version,
                  "changed": [k for k in before if before[k] != _rule_out(r)[k]]},
    )
    db.commit()
    return _rule_out(r)


@router.post("/learn-from-change/{change_id}")
def learn_from_change(change_id: str, user: User = Depends(require(Permission.PLAYBOOK_MANAGE)), db: Session = Depends(get_db)):
    """The learning flywheel: adopt a lawyer's edited redline as the rule's new
    preferred language, so the playbook improves every time a lawyer corrects it."""
    change = db.get(ProposedChange, change_id)
    if change is None:
        raise HTTPException(404, "proposed change not found")
    if not change.rule_key:
        raise HTTPException(400, "this change isn't tied to a playbook rule")
    if not change.after_text.strip():
        raise HTTPException(400, "nothing to learn — the change has no proposed language")

    pb = _active_playbook(db, user.org_id)
    r = db.execute(
        select(PlaybookRule).where(PlaybookRule.playbook_id == pb.id, PlaybookRule.rule_key == change.rule_key)
    ).scalars().first()
    if r is None:
        raise HTTPException(404, f"rule {change.rule_key} not found in the active playbook")

    r.preferred_body = change.after_text
    _bump_version(db, pb)
    db.flush()
    record_audit(
        db, org_id=user.org_id, action="playbook.rule.learned", resource_type="PlaybookRule", resource_id=r.id,
        actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"rule_key": r.rule_key, "from_change": change_id, "playbook_version": pb.version},
    )
    db.commit()
    return _rule_out(r)


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str, user: User = Depends(require(Permission.PLAYBOOK_MANAGE)), db: Session = Depends(get_db)):
    pb = _active_playbook(db, user.org_id)
    r = db.get(PlaybookRule, rule_id)
    if r is None or r.playbook_id != pb.id:
        raise HTTPException(404, "rule not found")
    key = r.rule_key
    db.delete(r)
    _bump_version(db, pb)
    db.flush()
    record_audit(
        db, org_id=user.org_id, action="playbook.rule.deleted", resource_type="PlaybookRule", resource_id=rule_id,
        actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"rule_key": key, "playbook_version": pb.version},
    )
    db.commit()
    return {"ok": True, "deleted": key}

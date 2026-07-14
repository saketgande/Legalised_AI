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
from ..models import ActorType, Playbook, PlaybookRule, ProposedChange, Request, ReviewRun, User
from ..permissions import RUNG_RANK, Permission
from ..security import require
from ..services.audit import record_audit
from ..services.playbooks import PlaybookResolutionError, resolve_playbook

router = APIRouter(prefix="/api/admin/playbook", tags=["playbook-admin"])

# a second, read-only surface the request forms use to offer a playbook picker —
# management stays under /api/admin/playbook (PLAYBOOK_MANAGE); this is a plain read
list_router = APIRouter(prefix="/api", tags=["playbook"])

_VALID_RUNGS = set(RUNG_RANK.keys())


class NewPlaybookIn(BaseModel):
    name: str


def _playbook_summary(db: Session, pb: Playbook) -> dict:
    count = db.execute(
        select(func.count(PlaybookRule.id)).where(PlaybookRule.playbook_id == pb.id)
    ).scalar_one()
    return {"id": pb.id, "name": pb.name, "version": pb.version, "active": pb.active, "rule_count": count}


def _list_playbooks(db: Session, org_id: str) -> list[dict]:
    rows = db.execute(
        select(Playbook).where(Playbook.org_id == org_id).order_by(Playbook.created_at.asc())
    ).scalars().all()
    return [_playbook_summary(db, pb) for pb in rows]


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
    # the position ladder: ordered acceptable retreats, each with its approval price
    fallbacks: list[dict] = []   # [{label, body, rung}]
    walk_away_text: str = ""     # the line we never cross


def _change_org(db: Session, change: ProposedChange) -> str | None:
    """A ProposedChange has no org of its own — resolve it via run -> request."""
    run = db.get(ReviewRun, change.run_id)
    if run is None:
        return None
    req = db.get(Request, run.request_id)
    return req.org_id if req else None


def _target_playbook(db: Session, org_id: str, playbook_id: str | None = None) -> Playbook:
    """The playbook a management action targets: the one named (org-checked), else
    the org's default. Translates the resolver's error to a 404."""
    try:
        return resolve_playbook(db, org_id, playbook_id)
    except PlaybookResolutionError as e:
        raise HTTPException(404, str(e))


def _rule_out(r: PlaybookRule) -> dict:
    return {
        "id": r.id, "rule_key": r.rule_key, "clause_type": r.clause_type, "heading": r.heading,
        "ordinal": r.ordinal, "preferred_position": r.preferred_position, "preferred_body": r.preferred_body,
        "rationale": r.rationale, "mandatory": r.mandatory, "deviation_rung": r.deviation_rung,
        "nda_type": (r.applies_when or {}).get("ndaType"),
        "fallbacks": r.fallbacks or [], "walk_away_text": r.walk_away_text or "",
    }


def _validate(payload: RuleIn) -> None:
    if payload.deviation_rung not in _VALID_RUNGS:
        raise HTTPException(400, f"deviation_rung must be one of {sorted(_VALID_RUNGS)}")
    if payload.nda_type not in (None, "MUTUAL", "ONE_WAY"):
        raise HTTPException(400, "nda_type must be MUTUAL, ONE_WAY, or null")
    if not payload.rule_key.strip() or not payload.heading.strip():
        raise HTTPException(400, "rule_key and heading are required")
    if len(payload.fallbacks) > 5:
        raise HTTPException(400, "at most 5 fallback positions")
    for i, fb in enumerate(payload.fallbacks):
        if not isinstance(fb, dict) or not str(fb.get("body", "")).strip():
            raise HTTPException(400, f"fallback #{i + 1} needs a body")
        # rung is required: the engine prices a missing rung at the full deviation
        # rung, so an implicit value would surprise the author either way
        if fb.get("rung") not in _VALID_RUNGS:
            raise HTTPException(400, f"fallback #{i + 1} needs a rung — one of {sorted(_VALID_RUNGS)}")


def _bump_version(db: Session, pb: Playbook) -> None:
    pb.version = (pb.version or 1) + 1


@list_router.get("/playbooks")
def list_playbooks_public(
    user: User = Depends(require(Permission.PLAYBOOK_READ)), db: Session = Depends(get_db),
):
    """Read-only catalog for the request forms' playbook picker."""
    return {"playbooks": _list_playbooks(db, user.org_id)}


@router.get("/catalog")
def list_playbooks(user: User = Depends(require(Permission.PLAYBOOK_MANAGE)), db: Session = Depends(get_db)):
    return {"playbooks": _list_playbooks(db, user.org_id)}


@router.post("/catalog")
def create_playbook(payload: NewPlaybookIn, user: User = Depends(require(Permission.PLAYBOOK_MANAGE)), db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "name is required")
    # new playbooks start inactive so they don't disturb the current default
    pb = Playbook(org_id=user.org_id, name=name, version=1, active=False)
    db.add(pb)
    db.flush()
    record_audit(
        db, org_id=user.org_id, action="playbook.created", resource_type="Playbook", resource_id=pb.id,
        actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"name": pb.name},
    )
    db.commit()
    return _playbook_summary(db, pb)


@router.post("/catalog/{playbook_id}/activate")
def activate_playbook(playbook_id: str, user: User = Depends(require(Permission.PLAYBOOK_MANAGE)), db: Session = Depends(get_db)):
    """Make this the org's default playbook (exactly one default at a time)."""
    pb = db.get(Playbook, playbook_id)
    if pb is None or pb.org_id != user.org_id:
        raise HTTPException(404, "playbook not found")
    others = db.execute(
        select(Playbook).where(Playbook.org_id == user.org_id, Playbook.active == True)  # noqa: E712
    ).scalars().all()
    for o in others:
        o.active = False
    pb.active = True
    db.flush()
    record_audit(
        db, org_id=user.org_id, action="playbook.activated", resource_type="Playbook", resource_id=pb.id,
        actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"name": pb.name, "deactivated": [o.id for o in others if o.id != pb.id]},
    )
    db.commit()
    return _playbook_summary(db, pb)


@router.get("")
def get_playbook(
    playbook_id: str | None = None,
    user: User = Depends(require(Permission.PLAYBOOK_MANAGE)), db: Session = Depends(get_db),
):
    pb = _target_playbook(db, user.org_id, playbook_id)
    rules = db.execute(
        select(PlaybookRule).where(PlaybookRule.playbook_id == pb.id).order_by(PlaybookRule.ordinal.asc())
    ).scalars().all()
    return {
        "playbook": {"id": pb.id, "name": pb.name, "version": pb.version, "active": pb.active},
        "rules": [_rule_out(r) for r in rules],
    }


@router.post("/rules")
def create_rule(
    payload: RuleIn, playbook_id: str | None = None,
    user: User = Depends(require(Permission.PLAYBOOK_MANAGE)), db: Session = Depends(get_db),
):
    _validate(payload)
    pb = _target_playbook(db, user.org_id, playbook_id)
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
        fallbacks=payload.fallbacks, walk_away_text=payload.walk_away_text,
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
def update_rule(
    rule_id: str, payload: RuleIn, playbook_id: str | None = None,
    user: User = Depends(require(Permission.PLAYBOOK_MANAGE)), db: Session = Depends(get_db),
):
    _validate(payload)
    pb = _target_playbook(db, user.org_id, playbook_id)
    r = db.get(PlaybookRule, rule_id)
    if r is None or r.playbook_id != pb.id:
        raise HTTPException(404, "rule not found")
    dupe = db.execute(
        select(PlaybookRule).where(
            PlaybookRule.playbook_id == pb.id,
            PlaybookRule.rule_key == payload.rule_key.strip(),
            PlaybookRule.id != rule_id,
        )
    ).scalars().first()
    if dupe:
        raise HTTPException(409, f"rule_key '{payload.rule_key}' already exists")
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
    r.fallbacks = payload.fallbacks
    r.walk_away_text = payload.walk_away_text
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
    # org-scope: a change from another organisation is not visible here (no cross-tenant learn)
    if _change_org(db, change) != user.org_id:
        raise HTTPException(404, "proposed change not found")
    # only learn from a lawyer's vetted edit — never raw/pending AI text or a rejected change
    if change.decision != "APPROVED_WITH_EDIT":
        raise HTTPException(409, "the flywheel only adopts a lawyer's edited redline (approve-with-edit)")
    if not change.rule_key:
        raise HTTPException(400, "this change isn't tied to a playbook rule")
    if not change.after_text.strip():
        raise HTTPException(400, "nothing to learn — the change has no proposed language")

    # adopt the edit into the playbook this change's request was reviewed against
    # (not blindly the org default), so the flywheel improves the right playbook
    run = db.get(ReviewRun, change.run_id)
    req = db.get(Request, run.request_id) if run else None
    pb = _target_playbook(db, user.org_id, req.playbook_id if req else None)
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
def delete_rule(
    rule_id: str, playbook_id: str | None = None,
    user: User = Depends(require(Permission.PLAYBOOK_MANAGE)), db: Session = Depends(get_db),
):
    pb = _target_playbook(db, user.org_id, playbook_id)
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

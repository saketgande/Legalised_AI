"""Routing rules admin + the request-type catalog.

Rules are WHEN -> THEN rows evaluated in order after classification. The
``preview`` endpoint is the dry-run: test candidate conditions against the
org's recent requests before activating — trust the rule because you watched
it match.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ActorType, RequestPriority, RoutingRule, User
from ..permissions import Permission, can
from ..security import current_user, require
from ..services.audit import record_audit
from ..services.request_types import list_types
from ..services.routing import preview_rule

router = APIRouter(prefix="/api", tags=["routing"])

_PRIORITIES = {p.value for p in RequestPriority}
# roles that legal work can be assigned to
_ASSIGNABLE_ROLES = {"paralegal", "attorney", "vp_legal", "gc", "legal_ops", "admin"}


@router.get("/users/assignable")
def assignable_users(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Minimal staff picker (id + name + role) for assignment UIs. Available to
    anyone who can decide reviews or manage intake — not the full admin surface."""
    if not (can(user.role, Permission.REVIEW_DECIDE) or can(user.role, Permission.INTAKE_MANAGE)):
        raise HTTPException(403, "not permitted")
    rows = db.execute(
        select(User).where(User.org_id == user.org_id, User.suspended == False)  # noqa: E712
        .order_by(User.name.asc())
    ).scalars().all()
    return {"users": [
        {"id": u.id, "name": u.name, "role": u.role}
        for u in rows if u.role in _ASSIGNABLE_ROLES
    ]}


# ————————————————— request-type catalog (any signed-in user; pickers need it) —————————————————
@router.get("/request-types")
def request_types(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {
        "types": [
            {
                "key": t.key, "label": t.label, "description": t.description,
                "category": t.category.value, "default_sla_hours": t.default_sla_hours,
            }
            for t in list_types(db, user.org_id)
        ]
    }


# ————————————————————————— routing rules (admin) —————————————————————————
class RuleIn(BaseModel):
    name: str
    ordinal: int = 0
    active: bool = True
    stop_on_match: bool = False
    match_type_key: str | None = None
    match_direction: str | None = None
    match_keyword: str | None = None
    match_jurisdiction: str | None = None
    set_assignee_user_id: str | None = None
    set_priority: str | None = None
    set_sla_hours: int | None = None
    escalate: bool = False


def _rule_out(db: Session, rule: RoutingRule) -> dict:
    assignee = db.get(User, rule.set_assignee_user_id) if rule.set_assignee_user_id else None
    return {
        "id": rule.id, "name": rule.name, "ordinal": rule.ordinal, "active": rule.active,
        "stop_on_match": rule.stop_on_match,
        "match_type_key": rule.match_type_key, "match_direction": rule.match_direction,
        "match_keyword": rule.match_keyword, "match_jurisdiction": rule.match_jurisdiction,
        "set_assignee_user_id": rule.set_assignee_user_id,
        "set_assignee_name": assignee.name if assignee else None,
        "set_priority": rule.set_priority, "set_sla_hours": rule.set_sla_hours,
        "escalate": rule.escalate,
    }


def _validate(db: Session, org_id: str, payload: RuleIn) -> None:
    if not payload.name.strip():
        raise HTTPException(400, "rule name is required")
    if payload.set_priority and payload.set_priority not in _PRIORITIES:
        raise HTTPException(400, f"priority must be one of {sorted(_PRIORITIES)}")
    if payload.match_direction and payload.match_direction not in ("OUTBOUND", "INBOUND"):
        raise HTTPException(400, "direction must be OUTBOUND or INBOUND")
    if payload.set_sla_hours is not None and payload.set_sla_hours <= 0:
        raise HTTPException(400, "SLA hours must be positive")
    if payload.set_assignee_user_id:
        assignee = db.get(User, payload.set_assignee_user_id)
        if assignee is None or assignee.org_id != org_id or assignee.suspended:
            raise HTTPException(400, "assignee must be an active user in your organisation")
    if not any([payload.match_type_key, payload.match_direction, payload.match_keyword,
                payload.match_jurisdiction]):
        raise HTTPException(400, "at least one condition is required (a rule that matches everything is a policy, not a rule)")
    if not any([payload.set_assignee_user_id, payload.set_priority, payload.set_sla_hours, payload.escalate]):
        raise HTTPException(400, "at least one action is required")


@router.get("/admin/routing/rules")
def list_rules(user: User = Depends(require(Permission.INTAKE_MANAGE)), db: Session = Depends(get_db)):
    rules = db.execute(
        select(RoutingRule).where(RoutingRule.org_id == user.org_id)
        .order_by(RoutingRule.ordinal.asc(), RoutingRule.created_at.asc())
    ).scalars().all()
    return {"rules": [_rule_out(db, r) for r in rules]}


@router.post("/admin/routing/rules")
def create_rule(
    payload: RuleIn,
    user: User = Depends(require(Permission.INTAKE_MANAGE)), db: Session = Depends(get_db),
):
    _validate(db, user.org_id, payload)
    rule = RoutingRule(org_id=user.org_id, **payload.model_dump())
    db.add(rule)
    db.flush()
    record_audit(
        db, org_id=user.org_id, action="routing.rule.created", resource_type="RoutingRule",
        resource_id=rule.id, actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"name": rule.name, "conditions": {
            "type": rule.match_type_key, "direction": rule.match_direction,
            "keyword": rule.match_keyword, "jurisdiction": rule.match_jurisdiction}},
    )
    db.commit()
    return _rule_out(db, rule)


@router.put("/admin/routing/rules/{rule_id}")
def update_rule(
    rule_id: str, payload: RuleIn,
    user: User = Depends(require(Permission.INTAKE_MANAGE)), db: Session = Depends(get_db),
):
    rule = db.get(RoutingRule, rule_id)
    if rule is None or rule.org_id != user.org_id:
        raise HTTPException(404, "rule not found")
    _validate(db, user.org_id, payload)
    before = {"name": rule.name, "active": rule.active}
    for k, v in payload.model_dump().items():
        setattr(rule, k, v)
    record_audit(
        db, org_id=user.org_id, action="routing.rule.updated", resource_type="RoutingRule",
        resource_id=rule.id, actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"before": before, "after": {"name": rule.name, "active": rule.active}},
    )
    db.commit()
    return _rule_out(db, rule)


@router.delete("/admin/routing/rules/{rule_id}")
def delete_rule(
    rule_id: str,
    user: User = Depends(require(Permission.INTAKE_MANAGE)), db: Session = Depends(get_db),
):
    rule = db.get(RoutingRule, rule_id)
    if rule is None or rule.org_id != user.org_id:
        raise HTTPException(404, "rule not found")
    record_audit(
        db, org_id=user.org_id, action="routing.rule.deleted", resource_type="RoutingRule",
        resource_id=rule.id, actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"name": rule.name},
    )
    db.delete(rule)
    db.commit()
    return {"ok": True, "deleted": rule_id}


class PreviewIn(BaseModel):
    match_type_key: str | None = None
    match_direction: str | None = None
    match_keyword: str | None = None
    match_jurisdiction: str | None = None


@router.post("/admin/routing/rules/preview")
def preview(
    payload: PreviewIn,
    user: User = Depends(require(Permission.INTAKE_MANAGE)), db: Session = Depends(get_db),
):
    """Dry-run: which of the last 50 requests would these conditions match?"""
    return preview_rule(db, user.org_id, payload.model_dump())

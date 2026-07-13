"""Admin: user management (list, invite, change role, suspend/reactivate).

Every mutation writes a chain-sealed audit row and is gated on
ADMIN_MANAGE_USERS. A guard prevents suspending or demoting the last admin so
the org always has a way back into admin tooling.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ActorType, User
from ..permissions import ROLE_PERMISSIONS, Permission
from ..security import current_user, hash_password, require
from ..services.audit import record_audit
from .auth import user_public

router = APIRouter(prefix="/api/admin", tags=["admin"])


class InviteUserIn(BaseModel):
    name: str
    email: str
    role: str
    password: str


class ChangeRoleIn(BaseModel):
    role: str


def _count_active_admins(db: Session, org_id: str) -> int:
    return db.execute(
        select(func.count(User.id)).where(
            User.org_id == org_id, User.role == "admin", User.suspended == False  # noqa: E712
        )
    ).scalar_one()


@router.get("/users")
def list_users(user: User = Depends(require(Permission.ADMIN_MANAGE_USERS)), db: Session = Depends(get_db)):
    rows = db.execute(select(User).where(User.org_id == user.org_id).order_by(User.name)).scalars().all()
    return [user_public(u) for u in rows]


@router.get("/roles")
def list_roles(_: User = Depends(require(Permission.ADMIN_MANAGE_USERS))):
    return {r: sorted(p.value for p in perms) for r, perms in ROLE_PERMISSIONS.items()}


@router.post("/users")
def invite_user(payload: InviteUserIn, actor: User = Depends(require(Permission.ADMIN_MANAGE_USERS)), db: Session = Depends(get_db)):
    if payload.role not in ROLE_PERMISSIONS:
        raise HTTPException(400, f"unknown role '{payload.role}'")
    existing = db.execute(
        select(User).where(func.lower(User.email) == payload.email.strip().lower())
    ).scalars().first()
    if existing:
        raise HTTPException(409, "a user with that email already exists")
    u = User(
        org_id=actor.org_id, name=payload.name, email=payload.email.strip().lower(),
        role=payload.role, password_hash=hash_password(payload.password),
    )
    db.add(u)
    db.flush()
    record_audit(
        db, org_id=actor.org_id, action="user.invited", resource_type="User", resource_id=u.id,
        actor_id=actor.id, actor_type=ActorType.USER, actor_label=actor.name,
        metadata={"email": u.email, "role": u.role},
    )
    db.commit()
    return user_public(u)


@router.patch("/users/{user_id}/role")
def change_role(user_id: str, payload: ChangeRoleIn, actor: User = Depends(require(Permission.ADMIN_MANAGE_USERS)), db: Session = Depends(get_db)):
    if payload.role not in ROLE_PERMISSIONS:
        raise HTTPException(400, f"unknown role '{payload.role}'")
    u = db.get(User, user_id)
    if u is None or u.org_id != actor.org_id:
        raise HTTPException(404, "user not found")
    if u.role == "admin" and payload.role != "admin" and _count_active_admins(db, actor.org_id) <= 1:
        raise HTTPException(409, "cannot demote the last admin")
    before = u.role
    u.role = payload.role
    record_audit(
        db, org_id=actor.org_id, action="user.role.changed", resource_type="User", resource_id=u.id,
        actor_id=actor.id, actor_type=ActorType.USER, actor_label=actor.name,
        metadata={"from": before, "to": u.role},
    )
    db.commit()
    return user_public(u)


@router.patch("/users/{user_id}/suspend")
def set_suspended(user_id: str, suspended: bool = True, actor: User = Depends(require(Permission.ADMIN_MANAGE_USERS)), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None or u.org_id != actor.org_id:
        raise HTTPException(404, "user not found")
    if suspended and u.role == "admin" and _count_active_admins(db, actor.org_id) <= 1:
        raise HTTPException(409, "cannot suspend the last admin")
    u.suspended = suspended
    record_audit(
        db, org_id=actor.org_id,
        action="user.suspended" if suspended else "user.reactivated",
        resource_type="User", resource_id=u.id,
        actor_id=actor.id, actor_type=ActorType.USER, actor_label=actor.name,
        metadata={"email": u.email},
    )
    db.commit()
    return user_public(u)

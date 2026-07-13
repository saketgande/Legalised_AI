"""Auth endpoints: login (email+password -> JWT) and me (whoami)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..permissions import permissions_for, rank_of
from ..security import current_user, issue_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


def user_public(user: User) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "rank": rank_of(user.role),
        "permissions": sorted(p.value for p in permissions_for(user.role)),
        "suspended": user.suspended,
    }


@router.post("/login")
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.execute(
        select(User).where(func.lower(User.email) == payload.email.strip().lower())
    ).scalars().first()
    if user is None or not user.password_hash or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "invalid email or password")
    if user.suspended:
        raise HTTPException(403, "account suspended")
    return {"token": issue_token(user), "user": user_public(user)}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_public(user)

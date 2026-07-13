"""Authentication: password hashing (stdlib pbkdf2, no native deps), JWT bearer
tokens, and the FastAPI dependencies that gate endpoints.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User
from .permissions import Permission, can, can_clear_rung

_PBKDF2_ROUNDS = 200_000


# ————————————————————————— passwords —————————————————————————
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2$sha256${_PBKDF2_ROUNDS}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, algo, rounds, salt_b64, dk_b64 = stored.split("$")
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(dk_b64)
        dk = hashlib.pbkdf2_hmac(algo, password.encode(), salt, int(rounds))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


# ————————————————————————— tokens —————————————————————————
def issue_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.id,
        "email": user.email,
        "role": user.role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.auth_token_ttl_hours)).timestamp()),
    }
    return jwt.encode(payload, settings.auth_secret, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.auth_secret, algorithms=["HS256"])


# ————————————————————————— dependencies —————————————————————————
def current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid or expired token")
    user = db.get(User, payload.get("sub"))
    if user is None:
        raise HTTPException(401, "user not found")
    if user.suspended:
        raise HTTPException(403, "account suspended")
    return user


def require(*perms: Permission):
    """Dependency factory: 403 unless the caller holds every listed permission."""
    def dep(user: User = Depends(current_user)) -> User:
        for p in perms:
            if not can(user.role, p):
                raise HTTPException(403, f"missing permission {p.value}")
        return user
    return dep


def assert_can_clear_rung(user: User, rung: str) -> None:
    if not can_clear_rung(user.role, rung):
        raise HTTPException(
            403,
            f"{user.role} cannot approve a {rung.replace('_', ' ')} sign-off — needs a more senior approver",
        )

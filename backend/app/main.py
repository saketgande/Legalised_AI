"""FastAPI entrypoint.

Creates tables on startup for the walking skeleton (a real deploy uses Alembic).
Mounts the request flow + meta routers and opens CORS to the Next.js dev origin.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .config import settings
from .db import Base, SessionLocal, engine
from .routers import admin, auth, inbound, meta, requests

app = FastAPI(title="Frontdoor — NDA wedge API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _ensure_auth_columns() -> None:
    """Additive, idempotent DDL — create_all doesn't ALTER existing tables, so a
    DB deployed before auth landed needs these columns added in place."""
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE app_user ADD COLUMN IF NOT EXISTS password_hash VARCHAR"))
        conn.execute(text("ALTER TABLE app_user ADD COLUMN IF NOT EXISTS suspended BOOLEAN DEFAULT FALSE"))


def _backfill_demo_auth() -> None:
    """Make an already-seeded DB loginnable: set the demo password on any user
    missing one, and ensure the requester + viewer demo logins exist."""
    from sqlalchemy import select

    from .models import Organization, User
    from .security import hash_password

    db = SessionLocal()
    try:
        org = db.execute(select(Organization)).scalars().first()
        if org is None:
            return
        pw = hash_password(settings.auth_demo_password)
        for u in db.execute(select(User).where(User.password_hash.is_(None))).scalars().all():
            u.password_hash = pw
        existing = {u.email.lower() for u in db.execute(select(User)).scalars().all()}
        for name, email, role in [
            ("Sam Carter", "sam.carter@northwind.example", "requester"),
            ("Val Ng", "val.ng@northwind.example", "viewer"),
        ]:
            if email not in existing:
                db.add(User(org_id=org.id, name=name, email=email, role=role, password_hash=pw))
        db.commit()
    finally:
        db.close()


@app.on_event("startup")
def _startup() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_auth_columns()
    if settings.seed_on_start:
        from .seed import seed

        seed()
    _backfill_demo_auth()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "frontdoor-api"}


app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(requests.router)
app.include_router(inbound.router)
app.include_router(meta.router)

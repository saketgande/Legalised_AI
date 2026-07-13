"""FastAPI entrypoint.

Creates tables on startup for the walking skeleton (a real deploy uses Alembic).
Mounts the request flow + meta routers and opens CORS to the Next.js dev origin.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .config import assert_production_secrets, settings
from .db import Base, SessionLocal, engine
from .routers import admin, auth, esign, inbound, intake, meta, playbook, requests

log = logging.getLogger("frontdoor")

app = FastAPI(title="Frontdoor — NDA wedge API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _run_migrations() -> None:
    """Alembic owns the schema. Fresh DB -> build from migrations. A legacy DB
    that predates Alembic (tables exist, no alembic_version) -> stamp head to
    adopt it without recreating. Already-managed DB -> apply new migrations."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    tables = set(inspect(engine).get_table_names())
    root = Path(__file__).resolve().parent.parent  # backend/
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)

    if "alembic_version" in tables:
        command.upgrade(cfg, "head")
    elif "app_user" in tables:
        log.info("adopting existing pre-Alembic schema (stamp head)")
        command.stamp(cfg, "head")
    else:
        command.upgrade(cfg, "head")


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
    assert_production_secrets()  # fail loud on insecure production config
    _run_migrations()            # Alembic: fresh -> build, legacy -> stamp
    if settings.seed_on_start:
        from .seed import seed

        seed()
    _backfill_demo_auth()


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    # never leak internals / stack traces to clients
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "frontdoor-api"}


@app.get("/api/health/ready")
def ready() -> dict:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"ok": False, "db": "unavailable"})
    return {"ok": True, "db": "up"}


app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(requests.router)
app.include_router(inbound.router)
app.include_router(intake.router)
app.include_router(esign.router)
app.include_router(playbook.router)
app.include_router(meta.router)

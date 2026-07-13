"""FastAPI entrypoint.

Creates tables on startup for the walking skeleton (a real deploy uses Alembic).
Mounts the request flow + meta routers and opens CORS to the Next.js dev origin.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import Base, engine
from .routers import inbound, meta, requests

app = FastAPI(title="Frontdoor — NDA wedge API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    Base.metadata.create_all(bind=engine)
    if settings.seed_on_start:
        # Idempotent: no-op once an organisation exists. Lets one-click deploys
        # come up with the playbook + reviewers already present.
        from .seed import seed

        seed()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "frontdoor-api"}


app.include_router(requests.router)
app.include_router(inbound.router)
app.include_router(meta.router)

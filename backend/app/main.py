"""FastAPI entrypoint.

Creates tables on startup for the walking skeleton (a real deploy uses Alembic).
Mounts the request flow + meta routers and opens CORS to the Next.js dev origin.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import Base, engine
from .routers import meta, requests

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


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "frontdoor-api"}


app.include_router(requests.router)
app.include_router(meta.router)

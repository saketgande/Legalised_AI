"""Supervisor-feed endpoint — the one decision stream.

`GET /api/decisions` returns the prioritized list of AI/pipeline work awaiting a
human call, plus a summary for the Daily-brief strip. Read-only aggregation;
the governed actions each card offers route through the existing approve / send /
renew / resolve endpoints (which do the auditing).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..security import current_user
from ..services import decisions as D

router = APIRouter(prefix="/api/decisions", tags=["decisions"])


@router.get("")
def feed(user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = D.list_decisions(db, user)
    return {"decisions": D.payload(items), "summary": D.summarize(items)}

"""Operations metrics endpoint — SLA compliance, deflection, turnaround.

Read-only aggregate over existing requests; gated identically to the reviewer
surfaces (REQUEST_READ_ALL). No new tables — pure computation.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..permissions import Permission
from ..security import require
from ..services.metrics import ops_metrics

router = APIRouter(prefix="/api/ops", tags=["ops"])


@router.get("/summary")
def ops_summary(
    user: User = Depends(require(Permission.REQUEST_READ_ALL)),
    db: Session = Depends(get_db),
):
    return ops_metrics(db, user.org_id)

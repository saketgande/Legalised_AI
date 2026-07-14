"""Workflow governance admin: the risk-ladder matrix (slice 2) and the
versioned workflow templates / designer (slice 4). Policy-as-data endpoints —
what these return IS what routes matters, so the UI renders governance live
from the same rows the engine reads."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ActorType, RequestCategory, User
from ..permissions import Permission
from ..security import require
from ..services.audit import record_audit
from ..services.request_types import (
    BANDS,
    default_risk_ladders,
    get_type,
    list_types,
    risk_matrix_for,
    validate_risk_ladders,
)

router = APIRouter(prefix="/api/admin/workflows", tags=["workflow-admin"])


class MatrixIn(BaseModel):
    risk_ladders: dict  # {"LOW": [...], "MEDIUM": [...], "HIGH": [...], "CRITICAL": [...]}


@router.get("/risk-matrix")
def get_risk_matrices(
    user: User = Depends(require(Permission.INTAKE_MANAGE)), db: Session = Depends(get_db),
):
    """Every CONTRACT type's effective band->rungs matrix — the live approval
    matrix, straight from the rows the intake engine reads."""
    out = []
    for t in list_types(db, user.org_id, active_only=False):
        if t.category != RequestCategory.CONTRACT:
            continue
        out.append({
            "type_key": t.key, "label": t.label, "active": t.active,
            "risk_ladders": risk_matrix_for(db, user.org_id, t.key),
            "is_default": not bool(t.risk_ladders),
            "bands": list(BANDS),
        })
    return {"matrices": out}


@router.put("/risk-matrix/{type_key}")
def put_risk_matrix(
    type_key: str, payload: MatrixIn,
    user: User = Depends(require(Permission.INTAKE_MANAGE)), db: Session = Depends(get_db),
):
    rt = get_type(db, user.org_id, type_key.lower())
    if rt is None:
        raise HTTPException(404, "unknown request type")
    if rt.category != RequestCategory.CONTRACT:
        raise HTTPException(400, "risk ladders only apply to CONTRACT types")
    problems = validate_risk_ladders(payload.risk_ladders, type_key=rt.key, category=rt.category)
    if problems:
        raise HTTPException(400, "; ".join(problems))
    before = risk_matrix_for(db, user.org_id, rt.key)
    rt.risk_ladders = payload.risk_ladders
    record_audit(
        db, org_id=user.org_id, action="governance.risk_matrix.updated",
        resource_type="RequestType", resource_id=rt.id,
        actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"type_key": rt.key, "before": before, "after": payload.risk_ladders},
    )
    db.commit()
    return {"ok": True, "type_key": rt.key, "risk_ladders": rt.risk_ladders}


@router.post("/risk-matrix/{type_key}/reset")
def reset_risk_matrix(
    type_key: str,
    user: User = Depends(require(Permission.INTAKE_MANAGE)), db: Session = Depends(get_db),
):
    rt = get_type(db, user.org_id, type_key.lower())
    if rt is None or rt.category != RequestCategory.CONTRACT:
        raise HTTPException(404, "unknown contract type")
    rt.risk_ladders = default_risk_ladders(rt.category, rt.key)
    record_audit(
        db, org_id=user.org_id, action="governance.risk_matrix.reset",
        resource_type="RequestType", resource_id=rt.id,
        actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"type_key": rt.key, "after": rt.risk_ladders},
    )
    db.commit()
    return {"ok": True, "type_key": rt.key, "risk_ladders": rt.risk_ladders}

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


class TemplateCreateIn(BaseModel):
    type_key: str
    name: str


class TemplateUpdateIn(BaseModel):
    name: str | None = None
    rungs: list | None = None


def _tpl_out(t) -> dict:
    return {
        "id": t.id, "type_key": t.type_key, "name": t.name, "version": t.version,
        "active": t.active, "rungs": t.rungs or [], "updated_at": t.updated_at,
    }


@router.get("")
def list_templates(
    user: User = Depends(require(Permission.INTAKE_MANAGE)), db: Session = Depends(get_db),
):
    from sqlalchemy import select

    from ..models import WorkflowTemplate
    from ..services.workflows import COND_FIELDS, GATE_RUNGS, KINDS, STAGE_ORDER

    rows = db.execute(
        select(WorkflowTemplate).where(WorkflowTemplate.org_id == user.org_id)
        .order_by(WorkflowTemplate.type_key.asc(), WorkflowTemplate.created_at.asc())
    ).scalars().all()
    return {
        "templates": [_tpl_out(t) for t in rows],
        "library": {"kinds": list(KINDS), "stages": STAGE_ORDER,
                    "cond_fields": COND_FIELDS, "gate_rungs": list(GATE_RUNGS)},
    }


@router.post("")
def create_template(
    payload: TemplateCreateIn,
    user: User = Depends(require(Permission.INTAKE_MANAGE)), db: Session = Depends(get_db),
):
    from ..models import WorkflowTemplate
    from ..services.workflows import default_rungs

    rt = get_type(db, user.org_id, payload.type_key.lower())
    if rt is None or rt.category != RequestCategory.CONTRACT:
        raise HTTPException(400, f"'{payload.type_key}' is not a CONTRACT request type")
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "a name is required")
    t = WorkflowTemplate(org_id=user.org_id, type_key=rt.key, name=name,
                         version=1, active=False, rungs=default_rungs(rt.key))
    db.add(t)
    db.flush()
    record_audit(
        db, org_id=user.org_id, action="workflow.template.created", resource_type="WorkflowTemplate",
        resource_id=t.id, actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"name": name, "type_key": rt.key},
    )
    db.commit()
    db.refresh(t)
    return _tpl_out(t)


@router.put("/{template_id}")
def update_template(
    template_id: str, payload: TemplateUpdateIn,
    user: User = Depends(require(Permission.INTAKE_MANAGE)), db: Session = Depends(get_db),
):
    from ..models import WorkflowTemplate
    from ..services.workflows import validate_rungs

    t = db.get(WorkflowTemplate, template_id)
    if t is None or t.org_id != user.org_id:
        raise HTTPException(404, "template not found")
    if payload.rungs is not None:
        problems = validate_rungs(payload.rungs)
        if problems:
            raise HTTPException(400, "; ".join(problems))
        t.rungs = payload.rungs
    if payload.name is not None and payload.name.strip():
        t.name = payload.name.strip()
    record_audit(
        db, org_id=user.org_id, action="workflow.template.updated", resource_type="WorkflowTemplate",
        resource_id=t.id, actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"name": t.name, "rung_keys": [r.get("key") for r in (t.rungs or [])]},
    )
    db.commit()
    db.refresh(t)
    return _tpl_out(t)


@router.post("/{template_id}/publish")
def publish_template(
    template_id: str,
    user: User = Depends(require(Permission.INTAKE_MANAGE)), db: Session = Depends(get_db),
):
    """Version bump. In-flight matters keep their pinned snapshot; only NEW
    matters instantiate the published version."""
    from ..models import WorkflowTemplate
    from ..services.workflows import validate_rungs

    t = db.get(WorkflowTemplate, template_id)
    if t is None or t.org_id != user.org_id:
        raise HTTPException(404, "template not found")
    problems = validate_rungs(t.rungs or [])
    if problems:
        raise HTTPException(400, "cannot publish an invalid template: " + "; ".join(problems))
    t.version += 1
    record_audit(
        db, org_id=user.org_id, action="workflow.template.published", resource_type="WorkflowTemplate",
        resource_id=t.id, actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"name": t.name, "version": t.version, "applies_to": "new matters only"},
    )
    db.commit()
    db.refresh(t)
    return _tpl_out(t)


@router.post("/{template_id}/activate")
def activate_template_route(
    template_id: str,
    user: User = Depends(require(Permission.INTAKE_MANAGE)), db: Session = Depends(get_db),
):
    from sqlalchemy import select

    from ..models import WorkflowTemplate

    t = db.get(WorkflowTemplate, template_id)
    if t is None or t.org_id != user.org_id:
        raise HTTPException(404, "template not found")
    siblings = db.execute(
        select(WorkflowTemplate).where(
            WorkflowTemplate.org_id == user.org_id,
            WorkflowTemplate.type_key == t.type_key,
            WorkflowTemplate.active == True,  # noqa: E712
        )
    ).scalars().all()
    for s in siblings:
        s.active = False
    db.flush()
    t.active = True
    record_audit(
        db, org_id=user.org_id, action="workflow.template.activated", resource_type="WorkflowTemplate",
        resource_id=t.id, actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"name": t.name, "type_key": t.type_key,
                  "deactivated": [s.name for s in siblings]},
    )
    db.commit()
    db.refresh(t)
    return _tpl_out(t)


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

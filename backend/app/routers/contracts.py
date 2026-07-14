"""Contract registry endpoints — the CLM half.

Read-only registry of executed contracts with renewal posture, plus a one-click
renew that spawns a fresh request through the standard intake pipeline. Gated on
the same request permissions as the rest of the app (read = REQUEST_READ_ALL,
renew = REQUEST_CREATE).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from pydantic import BaseModel

from ..db import get_db
from ..models import Request, User
from ..permissions import Permission
from ..security import require
from ..services.contracts import ContractError, contract_registry, start_renewal
from ..services.obligations import (
    ObligationError, extract_obligations_for_contract, list_obligations, resolve_obligation,
)

router = APIRouter(prefix="/api/contracts", tags=["contracts"])


@router.get("")
def list_contracts(
    user: User = Depends(require(Permission.REQUEST_READ_ALL)),
    db: Session = Depends(get_db),
):
    return contract_registry(db, user.org_id)


@router.get("/{contract_id}/obligations")
def contract_obligations(
    contract_id: str,
    user: User = Depends(require(Permission.REQUEST_READ_ALL)),
    db: Session = Depends(get_db),
):
    r = db.get(Request, contract_id)
    if r is None or r.org_id != user.org_id:
        raise HTTPException(404, "contract not found")
    # backfill for contracts executed before obligations shipped (idempotent)
    if r.executed_at is not None:
        extract_obligations_for_contract(db, r)
        db.commit()
    return {"obligations": list_obligations(db, user.org_id, contract_id)}


class ObligationResolveIn(BaseModel):
    done: bool = True  # False = waive


@router.post("/obligations/{obligation_id}/resolve")
def resolve_contract_obligation(
    obligation_id: str, payload: ObligationResolveIn,
    user: User = Depends(require(Permission.REVIEW_DECIDE)),
    db: Session = Depends(get_db),
):
    try:
        o = resolve_obligation(
            db, user.org_id, obligation_id, done=payload.done,
            actor_id=user.id, actor_name=user.name,
        )
    except ObligationError as e:
        raise HTTPException(404, str(e))
    db.commit()
    return {"ok": True, "id": o.id, "status": o.status.value}


@router.post("/{contract_id}/renew")
def renew_contract(
    contract_id: str,
    user: User = Depends(require(Permission.REQUEST_CREATE)),
    db: Session = Depends(get_db),
):
    try:
        renewal = start_renewal(
            db, user.org_id, contract_id, actor_id=user.id, actor_name=user.name
        )
    except ContractError as e:
        raise HTTPException(404, str(e))
    return {
        "id": renewal.id,
        "ref": renewal.ref,
        "state": renewal.state.value,
        "lane": renewal.lane.value if renewal.lane else None,
        "renewed_from_id": renewal.renewed_from_id,
    }

"""Contract registry endpoints — the CLM half.

Read-only registry of executed contracts with renewal posture, plus a one-click
renew that spawns a fresh request through the standard intake pipeline. Gated on
the same request permissions as the rest of the app (read = REQUEST_READ_ALL,
renew = REQUEST_CREATE).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..permissions import Permission
from ..security import require
from ..services.contracts import ContractError, contract_registry, start_renewal

router = APIRouter(prefix="/api/contracts", tags=["contracts"])


@router.get("")
def list_contracts(
    user: User = Depends(require(Permission.REQUEST_READ_ALL)),
    db: Session = Depends(get_db),
):
    return contract_registry(db, user.org_id)


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

"""DocuSign Connect webhook — flips a request to EXECUTED/FILED when the provider
reports the envelope completed. HMAC-verified when a Connect key is configured."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request as HttpRequest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import ActorType, Counterparty, Request, RequestState
from ..services.audit import record_audit

router = APIRouter(prefix="/api/esign", tags=["esign"])


def _verify_hmac(body: bytes, sig: str | None) -> bool:
    if not settings.docusign_connect_hmac:
        return True  # dev: no key configured -> skip verification
    if not sig:
        return False
    mac = hmac.new(settings.docusign_connect_hmac.encode(), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(mac).decode(), sig)


@router.post("/webhook")
async def docusign_webhook(
    request: HttpRequest,
    x_docusign_signature_1: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    body = await request.body()
    if not _verify_hmac(body, x_docusign_signature_1):
        raise HTTPException(401, "bad webhook signature")
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "invalid JSON")

    data = payload.get("data") or {}
    envelope_id = data.get("envelopeId") or payload.get("envelopeId")
    status = (data.get("envelopeSummary") or {}).get("status") or payload.get("status") or payload.get("event", "")
    if not envelope_id:
        return {"ok": True, "ignored": "no envelopeId"}

    r = db.execute(select(Request).where(Request.esign_envelope_id == envelope_id)).scalars().first()
    if r is None:
        return {"ok": True, "ignored": "unknown envelope"}

    status_l = str(status).lower()
    r.esign_status = status_l
    if "completed" in status_l and r.state == RequestState.OUT_FOR_SIGNATURE:
        cp = db.get(Counterparty, r.counterparty_id)
        r.state = RequestState.EXECUTED
        record_audit(
            db, org_id=r.org_id, action="request.executed", resource_type="Request", resource_id=r.id,
            actor_type=ActorType.SYSTEM, actor_label="DocuSign",
            metadata={"envelope_id": envelope_id, "countersigned_by": cp.name if cp else "counterparty"},
        )
        r.state = RequestState.FILED
        record_audit(
            db, org_id=r.org_id, action="request.filed", resource_type="Request", resource_id=r.id,
            actor_type=ActorType.SYSTEM, actor_label="System",
            metadata={"envelope_id": envelope_id, "provider": "docusign"},
        )
    db.commit()
    return {"ok": True}

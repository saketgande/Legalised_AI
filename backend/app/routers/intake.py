"""Multi-channel intake — email webhook + chatbot, both funneling into the same
`services/intake` pipeline the form uses. The only difference per channel is who
the requester is and which actor the audit attributes intake to.
"""
from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import ActorType, User
from ..permissions import Permission
from ..security import require
from ..services import intake
from ..services.ai import get_ai_client
from ..services.extract import extract_text
from . import requests as R

router = APIRouter(prefix="/api/intake", tags=["intake"])


# ————————————————————————— email webhook —————————————————————————
class Attachment(BaseModel):
    filename: str
    content_b64: str


class EmailWebhookIn(BaseModel):
    from_email: str
    from_name: str | None = None
    subject: str = ""
    body: str = ""
    attachment: Attachment | None = None


@router.post("/email-webhook")
def email_webhook(
    payload: EmailWebhookIn,
    x_intake_secret: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    # optional shared-secret gate (open in dev when unset)
    if settings.intake_webhook_secret and x_intake_secret != settings.intake_webhook_secret:
        raise HTTPException(401, "bad or missing X-Intake-Secret")

    org = intake.org_id(db)
    requester = intake.get_or_create_person(
        db, org, payload.from_name or payload.from_email, payload.from_email
    )
    actor = intake.Actor(None, ActorType.SYSTEM, "Email Intake")

    ai = get_ai_client()
    parsed = ai.parse_intake(f"{payload.subject}\n{payload.body}")

    # decide inbound (they sent a contract) vs outbound (they're asking for one)
    attachment_text = None
    if payload.attachment is not None:
        content = base64.b64decode(payload.attachment.content_b64)
        attachment_text = extract_text(payload.attachment.filename, content)

    is_inbound = (
        attachment_text is not None
        or parsed.intent == "inbound"
        or intake.looks_like_contract(payload.body)
    )

    if is_inbound:
        body_text = attachment_text or payload.body
        counterparty = parsed.counterparty or (payload.from_name or payload.from_email.split("@")[0].title())
        r = intake.create_inbound(
            db, org=org, requester=requester, actor=actor,
            counterparty_name=counterparty, nda_type=parsed.nda_type, purpose=parsed.purpose,
            body_text=body_text, channel="EMAIL", source="email" + ("-attachment" if attachment_text else ""),
        )
        return {"created": True, "classified": "inbound", "request": R._summary(db, r)}

    if not parsed.counterparty:
        return {"created": False, "classified": "outbound",
                "reply": "Couldn't identify the counterparty from the email — a human should triage this."}

    r = intake.create_outbound(
        db, org=org, requester=requester, actor=actor,
        counterparty_name=parsed.counterparty, nda_type=parsed.nda_type, purpose=parsed.purpose,
        jurisdiction=parsed.jurisdiction, term_months=parsed.term_months, channel="EMAIL",
    )
    return {"created": True, "classified": "outbound", "request": R._summary(db, r)}


# ————————————————————————— chatbot —————————————————————————
class ChatIn(BaseModel):
    message: str


@router.post("/chat")
def chat(
    payload: ChatIn,
    user: User = Depends(require(Permission.REQUEST_CREATE)),
    db: Session = Depends(get_db),
):
    ai = get_ai_client()
    parsed = ai.parse_intake(payload.message)

    if parsed.intent == "inbound":
        return {"reply": "To review a counterparty's NDA, head to “Review their paper” and paste "
                          "or upload their document — I'll redline it against the playbook.",
                "created": None, "extracted": _extracted(parsed)}

    if not parsed.counterparty:
        return {"reply": parsed.reply, "created": None, "extracted": _extracted(parsed)}

    requester = intake.get_or_create_person(db, user.org_id, user.name, user.email)
    r = intake.create_outbound(
        db, org=user.org_id, requester=requester,
        actor=intake.Actor(user.id, ActorType.USER, user.name),
        counterparty_name=parsed.counterparty, nda_type=parsed.nda_type, purpose=parsed.purpose,
        jurisdiction=parsed.jurisdiction, term_months=parsed.term_months, channel="CHAT",
    )
    return {
        "reply": parsed.reply,
        "created": {"id": r.id, "ref": r.ref, "lane": r.lane.value if r.lane else None,
                    "state": r.state.value, "counterparty": parsed.counterparty},
        "extracted": _extracted(parsed),
    }


def _extracted(p) -> dict:
    return {
        "intent": p.intent, "counterparty": p.counterparty, "nda_type": p.nda_type,
        "purpose": p.purpose, "term_months": p.term_months, "jurisdiction": p.jurisdiction,
        "model": p.model, "confidence": p.confidence,
    }

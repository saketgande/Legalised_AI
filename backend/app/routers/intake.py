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
from ..services.playbooks import PlaybookResolutionError
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

    from ..services.email_intake import ingest_email

    org = intake.org_id(db)
    attachments: list[tuple[str, bytes]] = []
    if payload.attachment is not None:
        attachments.append((payload.attachment.filename, base64.b64decode(payload.attachment.content_b64)))

    res = ingest_email(
        db, org=org, from_email=payload.from_email, from_name=payload.from_name,
        subject=payload.subject, body=payload.body, attachments=attachments, source="email",
    )
    if res.created and res.request_id is not None:
        from ..models import Request
        r = db.get(Request, res.request_id)
        return {"created": True, "classified": res.classified, "request": R._summary(db, r)}
    return {"created": False, "classified": res.classified, "reply": res.reply}


@router.post("/email/poll-cron")
def email_poll_cron(
    x_intake_secret: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Poll every active mailbox once. Authorised by the shared intake secret so an
    external scheduler (Render Cron / GitHub Actions) can drive polling without a
    user session — the in-process loop covers the always-on case."""
    if not settings.intake_webhook_secret or x_intake_secret != settings.intake_webhook_secret:
        raise HTTPException(401, "bad or missing X-Intake-Secret")
    from ..services.email_poller import poll_all_active

    return poll_all_active(db)


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

    if parsed.intent == "advice":
        # a question for the legal team -> the ADVICE resolution engine
        requester = intake.get_or_create_person(db, user.org_id, user.name, user.email)
        r = intake.create_advice(
            db, org=user.org_id, requester=requester,
            actor=intake.Actor(user.id, ActorType.USER, user.name),
            type_key="legal_question", question=payload.message, channel="CHAT",
        )
        return {
            "reply": parsed.reply or "Got it — I've filed that as a question for the legal team.",
            "created": {"id": r.id, "ref": r.ref, "lane": r.lane.value if r.lane else None,
                        "state": r.state.value, "counterparty": "Legal question"},
            "extracted": _extracted(parsed),
        }

    if not parsed.counterparty:
        return {"reply": parsed.reply, "created": None, "extracted": _extracted(parsed)}

    requester = intake.get_or_create_person(db, user.org_id, user.name, user.email)
    # explicit DPA asks run the DPA engine (never AUTO — the type gate applies);
    # if the org has no DPA catalog/playbook, fall back to the NDA pipeline
    tkey = intake.detect_contract_type(payload.message)
    try:
        r = intake.create_outbound(
            db, org=user.org_id, requester=requester,
            actor=intake.Actor(user.id, ActorType.USER, user.name),
            counterparty_name=parsed.counterparty, nda_type=parsed.nda_type, purpose=parsed.purpose,
            jurisdiction=parsed.jurisdiction, term_months=parsed.term_months, channel="CHAT",
            type_key=tkey,
        )
    except (ValueError, PlaybookResolutionError):
        if tkey == "nda":
            raise
        db.rollback()
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

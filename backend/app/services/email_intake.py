"""Turn an email into a filed intake request.

This is the shared "understand → follow the plan" core: given a message (from,
subject, body, optional attachments), the assistant classifies intent, decides
inbound (they sent us a contract to review) vs outbound (they're asking us to
draft one), and files it through the same pipeline the form and chatbot use.

Both the email webhook and the IMAP poller call ``ingest_email`` — the only
difference between channels is how the message arrived.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..models import ActorType
from . import intake
from .ai import get_ai_client
from .extract import extract_text
from .playbooks import PlaybookResolutionError

# attachment types we can pull clause text out of
_SUPPORTED_EXT = (".docx", ".pdf", ".txt", ".md")


@dataclass
class IngestResult:
    created: bool
    classified: str                 # "inbound" | "outbound"
    request_id: str | None = None
    ref: str | None = None
    direction: str | None = None
    counterparty: str | None = None
    reply: str | None = None        # set when nothing was created (needs a human)


def _first_supported_attachment(attachments: list[tuple[str, bytes]]) -> tuple[str, bytes] | None:
    for name, content in attachments or []:
        if name.lower().endswith(_SUPPORTED_EXT):
            return name, content
    return None


def ingest_email(
    db: Session, *, org: str, from_email: str, from_name: str | None = None,
    subject: str = "", body: str = "", attachments: list[tuple[str, bytes]] | None = None,
    actor_label: str = "Email Intake", source: str = "email", playbook_id: str | None = None,
) -> IngestResult:
    from ..routers import requests as R  # local import avoids a router<->service cycle

    requester = intake.get_or_create_person(db, org, from_name or from_email, from_email)
    actor = intake.Actor(None, ActorType.SYSTEM, actor_label)

    ai = get_ai_client()
    parsed = ai.parse_intake(f"{subject}\n{body}")

    # an attachment we can read (their paper) is a strong inbound signal
    attachment_text: str | None = None
    att = _first_supported_attachment(attachments or [])
    if att is not None:
        try:
            attachment_text = extract_text(att[0], att[1])
        except Exception:
            attachment_text = None  # unreadable attachment -> fall back to the body

    is_inbound = (
        attachment_text is not None
        or parsed.intent == "inbound"
        or intake.looks_like_contract(body)
    )

    # explicit DPA asks route to the DPA engine; anything ambiguous stays NDA.
    # Misdetection errs safe — non-NDA contract types always get attorney review.
    tkey = intake.detect_contract_type(f"{subject}\n{body}")

    if is_inbound:
        body_text = attachment_text or body
        counterparty = parsed.counterparty or (from_name or from_email.split("@")[0].title())
        try:
            r = intake.create_inbound(
                db, org=org, requester=requester, actor=actor,
                counterparty_name=counterparty, nda_type=parsed.nda_type, purpose=parsed.purpose,
                body_text=body_text, channel="EMAIL",
                source=source + ("-attachment" if attachment_text else ""),
                # the mailbox's pinned playbook is NDA-only; a detected DPA
                # resolves against the org's DPA default instead
                playbook_id=playbook_id if tkey == "nda" else None,
                type_key=tkey,
            )
        except (ValueError, PlaybookResolutionError):
            if tkey == "nda":
                raise
            # no DPA catalog entry / no DPA playbook in this org — never wedge
            # the mailbox on it; fall back to the NDA pipeline
            db.rollback()
            r = intake.create_inbound(
                db, org=org, requester=requester, actor=actor,
                counterparty_name=counterparty, nda_type=parsed.nda_type, purpose=parsed.purpose,
                body_text=body_text, channel="EMAIL",
                source=source + ("-attachment" if attachment_text else ""),
                playbook_id=playbook_id,
            )
        return IngestResult(created=True, classified="inbound", request_id=r.id, ref=r.ref,
                            direction="INBOUND", counterparty=counterparty)

    if parsed.intent == "advice":
        # a question for the legal team, not a contract ask -> the ADVICE engine
        r = intake.create_advice(
            db, org=org, requester=requester, actor=actor,
            type_key="legal_question", question=f"{subject}\n\n{body}".strip(), channel="EMAIL",
        )
        return IngestResult(created=True, classified="advice", request_id=r.id, ref=r.ref,
                            direction="OUTBOUND", counterparty="Legal question")

    if not parsed.counterparty:
        return IngestResult(
            created=False, classified="outbound",
            reply="Couldn't identify the counterparty from the email — a human should triage this.",
        )

    try:
        r = intake.create_outbound(
            db, org=org, requester=requester, actor=actor,
            counterparty_name=parsed.counterparty, nda_type=parsed.nda_type, purpose=parsed.purpose,
            jurisdiction=parsed.jurisdiction, term_months=parsed.term_months, channel="EMAIL",
            playbook_id=playbook_id if tkey == "nda" else None, type_key=tkey,
        )
    except (ValueError, PlaybookResolutionError):
        if tkey == "nda":
            raise
        db.rollback()
        r = intake.create_outbound(
            db, org=org, requester=requester, actor=actor,
            counterparty_name=parsed.counterparty, nda_type=parsed.nda_type, purpose=parsed.purpose,
            jurisdiction=parsed.jurisdiction, term_months=parsed.term_months, channel="EMAIL",
            playbook_id=playbook_id,
        )
    return IngestResult(created=True, classified="outbound", request_id=r.id, ref=r.ref,
                        direction="OUTBOUND", counterparty=parsed.counterparty)

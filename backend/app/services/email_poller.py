"""IMAP inbox polling — the real email channel.

Connects to a configured legal inbox, pulls the messages that haven't been seen
yet, and funnels each through ``email_intake.ingest_email`` (understand → file).
Processed messages are marked ``\\Seen`` so they're ingested exactly once.

The IMAP connection is injected (``connect=``) so the whole path — parse a real
RFC822 message, classify it, create the request — is testable against a fake
mailbox with no network. In production ``_default_connect`` opens a real
``imaplib`` session.
"""
from __future__ import annotations

import email
import imaplib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import EmailMailbox
from .email_intake import IngestResult, ingest_email
from .secrets import unseal

log = logging.getLogger("frontdoor.email")

_MAX_PER_POLL = 25            # cap messages handled per poll so one run stays bounded
_MAX_ATTACH_BYTES = 10 * 1024 * 1024
_CONNECT_TIMEOUT = 15         # seconds — fail fast on a bad host instead of hanging the poller


# ————————————————————————— connection —————————————————————————
def _default_connect(mailbox: EmailMailbox) -> imaplib.IMAP4:
    cls = imaplib.IMAP4_SSL if mailbox.use_ssl else imaplib.IMAP4
    conn = cls(mailbox.imap_host, mailbox.imap_port, timeout=_CONNECT_TIMEOUT)
    conn.login(mailbox.username, unseal(mailbox.secret_enc))
    return conn


# ————————————————————————— parsing —————————————————————————
def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_message(raw: bytes) -> dict:
    """RFC822 bytes -> {from_email, from_name, subject, body, attachments}."""
    msg = email.message_from_bytes(raw)
    from_name, from_email = parseaddr(_decode(msg.get("From")))
    subject = _decode(msg.get("Subject"))

    text_body = ""
    html_body = ""
    attachments: list[tuple[str, bytes]] = []

    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue
            disp = str(part.get("Content-Disposition") or "")
            ctype = part.get_content_type()
            filename = part.get_filename()
            if "attachment" in disp.lower() or filename:
                payload = part.get_payload(decode=True) or b""
                if filename and 0 < len(payload) <= _MAX_ATTACH_BYTES:
                    attachments.append((_decode(filename), payload))
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                decoded = payload.decode(charset, errors="replace")
            except LookupError:
                decoded = payload.decode("utf-8", errors="replace")
            if ctype == "text/plain":
                text_body += decoded
            elif ctype == "text/html":
                html_body += decoded
    else:
        payload = msg.get_payload(decode=True) or b""
        charset = msg.get_content_charset() or "utf-8"
        try:
            decoded = payload.decode(charset, errors="replace")
        except LookupError:
            decoded = payload.decode("utf-8", errors="replace")
        if msg.get_content_type() == "text/html":
            html_body = decoded
        else:
            text_body = decoded

    body = text_body.strip() or _strip_html(html_body)
    return {
        "from_email": from_email or "unknown@unknown",
        "from_name": from_name or None,
        "subject": subject,
        "body": body,
        "attachments": attachments,
    }


# ————————————————————————— test connection —————————————————————————
def test_connection(mailbox: EmailMailbox, connect=_default_connect) -> dict:
    try:
        conn = connect(mailbox)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    try:
        status, data = conn.select(mailbox.folder, readonly=True)
        if status != "OK":
            return {"ok": False, "error": f"cannot open folder {mailbox.folder!r}"}
        total = int(data[0]) if data and data[0] else 0
        us, ud = conn.uid("search", None, "UNSEEN")
        unseen = len(ud[0].split()) if us == "OK" and ud and ud[0] else 0
        return {"ok": True, "folder": mailbox.folder, "total": total, "unseen": unseen}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        try:
            conn.logout()
        except Exception:
            pass


# ————————————————————————— poll —————————————————————————
@dataclass
class MessageOutcome:
    uid: str
    from_email: str
    subject: str
    result: IngestResult | None
    error: str | None = None


def poll_mailbox(db: Session, mailbox: EmailMailbox, connect=_default_connect, limit: int = _MAX_PER_POLL) -> dict:
    """Drain UNSEEN messages from one mailbox through the intake pipeline.

    Best-effort per message: one bad message is recorded and skipped, never
    aborting the batch. Only successfully-ingested messages are marked Seen, so a
    transient failure is retried on the next poll.
    """
    outcomes: list[MessageOutcome] = []
    error: str | None = None
    try:
        conn = connect(mailbox)
    except Exception as e:  # noqa: BLE001
        error = f"connect failed: {type(e).__name__}: {e}"
        mailbox.last_polled_at = datetime.now(timezone.utc)
        mailbox.last_error = error
        db.commit()
        return {"ok": False, "error": error, "polled": 0, "ingested": 0, "messages": []}

    try:
        status, _ = conn.select(mailbox.folder)
        if status != "OK":
            raise RuntimeError(f"cannot open folder {mailbox.folder!r}")
        s, d = conn.uid("search", None, "UNSEEN")
        uids = d[0].split() if s == "OK" and d and d[0] else []
        uids = uids[:limit]

        for uid in uids:
            uid_s = uid.decode() if isinstance(uid, bytes) else str(uid)
            try:
                fs, fd = conn.uid("fetch", uid, "(RFC822)")
                if fs != "OK" or not fd or not fd[0]:
                    raise RuntimeError("fetch failed")
                raw = fd[0][1]
                parsed = parse_message(raw)
                res = ingest_email(
                    db, org=mailbox.org_id,
                    from_email=parsed["from_email"], from_name=parsed["from_name"],
                    subject=parsed["subject"], body=parsed["body"],
                    attachments=parsed["attachments"],
                    actor_label="Email Intake", source="email-poll",
                    playbook_id=mailbox.default_playbook_id,
                )
                # only now that it's filed do we mark it read (idempotent ingest)
                conn.uid("store", uid, "+FLAGS", "\\Seen")
                if res.created:
                    mailbox.ingested_count = (mailbox.ingested_count or 0) + 1
                outcomes.append(MessageOutcome(uid_s, parsed["from_email"], parsed["subject"], res))
            except Exception as e:  # noqa: BLE001
                log.exception("email-poll: message %s failed", uid_s)
                # a failed flush (e.g. a concurrent-return IntegrityError) poisons
                # the shared session — roll back so the REST of the batch, and the
                # final bookkeeping commit, still succeed
                try:
                    db.rollback()
                except Exception:
                    pass
                outcomes.append(MessageOutcome(uid_s, "", "", None, error=f"{type(e).__name__}: {e}"))
    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {e}"
    finally:
        try:
            conn.logout()
        except Exception:
            pass

    ingested = sum(1 for o in outcomes if o.result and o.result.created)
    mailbox.last_polled_at = datetime.now(timezone.utc)
    mailbox.last_error = error
    mailbox.last_result = {
        "polled": len(outcomes), "ingested": ingested,
        "at": mailbox.last_polled_at.isoformat(),
    }
    db.commit()

    return {
        "ok": error is None,
        "error": error,
        "polled": len(outcomes),
        "ingested": ingested,
        "messages": [
            {
                "uid": o.uid, "from": o.from_email, "subject": o.subject,
                "created": bool(o.result and o.result.created),
                "classified": o.result.classified if o.result else None,
                "ref": o.result.ref if o.result else None,
                "request_id": o.result.request_id if o.result else None,
                "direction": o.result.direction if o.result else None,
                "reply": o.result.reply if o.result else None,
                "error": o.error,
            }
            for o in outcomes
        ],
    }


def poll_all_active(db: Session, connect=_default_connect) -> dict:
    """Poll every active mailbox (the background loop + cron trigger entry point)."""
    boxes = db.execute(select(EmailMailbox).where(EmailMailbox.active == True)).scalars().all()  # noqa: E712
    results = []
    total = 0
    for mb in boxes:
        r = poll_mailbox(db, mb, connect=connect)
        results.append({"org_id": mb.org_id, **{k: r[k] for k in ("ok", "polled", "ingested", "error")}})
        total += r["ingested"]
    return {"mailboxes": len(boxes), "ingested": total, "results": results}

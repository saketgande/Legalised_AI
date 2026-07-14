"""Admin config for the polled legal inbox.

Gated on INTAKE_MANAGE (admin / GC / legal-ops). The password is sealed before it
touches the DB; it's never returned. "Test" opens an IMAP session without
ingesting; "Poll now" drains the inbox through the pipeline immediately.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ActorType, EmailMailbox, Playbook, User
from ..permissions import Permission
from ..security import require
from ..services.audit import record_audit
from ..services.email_poller import poll_mailbox, test_connection
from ..services.secrets import seal

router = APIRouter(prefix="/api/admin/intake", tags=["intake-admin"])


class MailboxIn(BaseModel):
    imap_host: str
    imap_port: int = 993
    use_ssl: bool = True
    username: str
    password: str | None = None          # omit on edit to keep the stored secret
    folder: str = "INBOX"
    active: bool = True
    default_playbook_id: str | None = None


def _mailbox(db: Session, org_id: str) -> EmailMailbox | None:
    return db.execute(select(EmailMailbox).where(EmailMailbox.org_id == org_id)).scalars().first()


def _out(mb: EmailMailbox | None) -> dict:
    if mb is None:
        return {"configured": False}
    return {
        "configured": True,
        "imap_host": mb.imap_host,
        "imap_port": mb.imap_port,
        "use_ssl": mb.use_ssl,
        "username": mb.username,
        "folder": mb.folder,
        "active": mb.active,
        "default_playbook_id": mb.default_playbook_id,
        "last_polled_at": mb.last_polled_at.isoformat() if mb.last_polled_at else None,
        "last_error": mb.last_error,
        "last_result": mb.last_result or {},
        "ingested_count": mb.ingested_count or 0,
    }


@router.get("/mailbox")
def get_mailbox(user: User = Depends(require(Permission.INTAKE_MANAGE)), db: Session = Depends(get_db)):
    return _out(_mailbox(db, user.org_id))


@router.put("/mailbox")
def upsert_mailbox(payload: MailboxIn, user: User = Depends(require(Permission.INTAKE_MANAGE)), db: Session = Depends(get_db)):
    if not payload.imap_host.strip() or not payload.username.strip():
        raise HTTPException(400, "imap_host and username are required")
    if payload.default_playbook_id:
        pb = db.get(Playbook, payload.default_playbook_id)
        if pb is None or pb.org_id != user.org_id:
            raise HTTPException(400, "default_playbook_id not found for organisation")
        # the email channel is NDA-only today (parse_intake extracts no contract
        # type); pinning e.g. a DPA book here would make every polled message fail
        # the resolver's type check and re-fail forever
        if (pb.contract_type_key or "nda").lower() != "nda":
            raise HTTPException(
                400,
                f"the email channel drafts and reviews NDAs — pick an NDA playbook, "
                f"not a {pb.contract_type_key} one",
            )

    mb = _mailbox(db, user.org_id)
    creating = mb is None
    if creating:
        if not payload.password:
            raise HTTPException(400, "password is required when first connecting a mailbox")
        mb = EmailMailbox(org_id=user.org_id, imap_host="", username="", secret_enc="")
        db.add(mb)

    mb.imap_host = payload.imap_host.strip()
    mb.imap_port = payload.imap_port
    mb.use_ssl = payload.use_ssl
    mb.username = payload.username.strip()
    mb.folder = payload.folder.strip() or "INBOX"
    mb.active = payload.active
    mb.default_playbook_id = payload.default_playbook_id or None
    if payload.password:                       # only reseal when a new password is supplied
        mb.secret_enc = seal(payload.password)
    mb.updated_at = datetime.now(timezone.utc)
    db.flush()

    record_audit(
        db, org_id=user.org_id, action="intake.mailbox." + ("connected" if creating else "updated"),
        resource_type="EmailMailbox", resource_id=mb.id,
        actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"host": mb.imap_host, "username": mb.username, "active": mb.active},
    )
    db.commit()
    return _out(mb)


@router.post("/mailbox/test")
def test_mailbox(user: User = Depends(require(Permission.INTAKE_MANAGE)), db: Session = Depends(get_db)):
    mb = _mailbox(db, user.org_id)
    if mb is None:
        raise HTTPException(404, "no mailbox configured")
    return test_connection(mb)


@router.post("/mailbox/poll")
def poll_now(user: User = Depends(require(Permission.INTAKE_MANAGE)), db: Session = Depends(get_db)):
    mb = _mailbox(db, user.org_id)
    if mb is None:
        raise HTTPException(404, "no mailbox configured")
    result = poll_mailbox(db, mb)
    record_audit(
        db, org_id=user.org_id, action="intake.mailbox.polled",
        resource_type="EmailMailbox", resource_id=mb.id,
        actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name,
        metadata={"polled": result.get("polled"), "ingested": result.get("ingested"), "trigger": "manual"},
    )
    db.commit()
    return result


@router.delete("/mailbox")
def delete_mailbox(user: User = Depends(require(Permission.INTAKE_MANAGE)), db: Session = Depends(get_db)):
    mb = _mailbox(db, user.org_id)
    if mb is None:
        raise HTTPException(404, "no mailbox configured")
    mb_id = mb.id
    db.delete(mb)
    db.flush()
    record_audit(
        db, org_id=user.org_id, action="intake.mailbox.disconnected",
        resource_type="EmailMailbox", resource_id=mb_id,
        actor_id=user.id, actor_type=ActorType.USER, actor_label=user.name, metadata={},
    )
    db.commit()
    return {"ok": True}

"""The email channel: parse a real RFC822 message, classify it, and file it
through the intake pipeline — driven by a fake IMAP mailbox (no network)."""
from email.message import EmailMessage

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Direction, EmailMailbox, Organization, Playbook, Request
from app.services import email_poller as EP
from app.services.secrets import seal, unseal

CONTRACT = (
    "1. Confidential Information\n"
    "\"Confidential Information\" means any information disclosed by the parties.\n\n"
    "2. Term\n"
    "This Agreement shall remain in effect for sixty (60) months.\n\n"
    "3. Governing Law\n"
    "This Agreement is governed by the laws of England and Wales.\n"
)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _mailbox(db):
    org = Organization(name="Northwind")
    db.add(org)
    db.flush()
    db.add(Playbook(org_id=org.id, name="Standard", version=1, active=True))
    mb = EmailMailbox(
        org_id=org.id, imap_host="imap.example", imap_port=993, use_ssl=True,
        username="legal@northwind.example", secret_enc=seal("app-password"), folder="INBOX", active=True,
    )
    db.add(mb)
    db.flush()
    return mb


def _msg_plain(frm, subject, body) -> bytes:
    m = EmailMessage()
    m["From"] = frm
    m["Subject"] = subject
    m.set_content(body)
    return m.as_bytes()


def _msg_with_attachment(frm, subject, body, filename, attach_text) -> bytes:
    m = EmailMessage()
    m["From"] = frm
    m["Subject"] = subject
    m.set_content(body)
    m.add_attachment(attach_text.encode(), maintype="text", subtype="plain", filename=filename)
    return m.as_bytes()


class FakeIMAP:
    """Mimics the tiny imaplib surface poll_mailbox uses."""
    def __init__(self, messages: list[bytes]):
        self.messages = messages
        self.stored: list = []
        self.logged_in = False

    def login(self, user, password):
        self.logged_in = True
        return ("OK", [b"LOGIN completed"])

    def select(self, folder, readonly=False):
        return ("OK", [str(len(self.messages)).encode()])

    def uid(self, command, *args):
        cmd = command.lower()
        if cmd == "search":
            uids = b" ".join(str(i + 1).encode() for i in range(len(self.messages)))
            return ("OK", [uids])
        if cmd == "fetch":
            uid = args[0]
            idx = int(uid.decode() if isinstance(uid, bytes) else uid) - 1
            return ("OK", [(b"%d (RFC822)" % (idx + 1), self.messages[idx])])
        if cmd == "store":
            self.stored.append(args[0])
            return ("OK", [b""])
        return ("OK", [b""])

    def logout(self):
        return ("BYE", [b"logout"])


# ————————————————————————— seal / unseal —————————————————————————
def test_seal_roundtrip_and_not_plaintext():
    sealed = seal("hunter2")
    assert sealed != "hunter2"
    assert "hunter2" not in sealed
    assert unseal(sealed) == "hunter2"


# ————————————————————————— parse_message —————————————————————————
def test_parse_message_extracts_from_subject_body_attachment():
    raw = _msg_with_attachment(
        "Jordan Lee <jordan@bigco.example>", "NDA attached", "Please review the attached NDA.",
        "their_nda.txt", CONTRACT,
    )
    p = EP.parse_message(raw)
    assert p["from_email"] == "jordan@bigco.example"
    assert p["from_name"] == "Jordan Lee"
    assert p["subject"] == "NDA attached"
    assert "review the attached" in p["body"]
    assert len(p["attachments"]) == 1
    assert p["attachments"][0][0] == "their_nda.txt"
    assert b"Confidential Information" in p["attachments"][0][1]


# ————————————————————————— poll_mailbox (full path) —————————————————————————
def test_poll_ingests_unseen_and_marks_seen(db):
    mb = _mailbox(db)
    messages = [
        _msg_plain("Globex Legal <legal@globex.example>", "Our NDA for signature", CONTRACT),
        _msg_with_attachment("Jordan <jordan@bigco.example>", "NDA attached",
                             "Please review the attached NDA.", "nda.txt", CONTRACT),
    ]
    fake = FakeIMAP(messages)
    result = EP.poll_mailbox(db, mb, connect=lambda _mb: fake)

    assert result["ok"] is True
    assert result["polled"] == 2
    assert result["ingested"] == 2
    # both messages became requests
    reqs = db.execute(select(Request)).scalars().all()
    assert len(reqs) == 2
    # a counterparty contract classifies as INBOUND (their paper -> we review)
    assert all(r.direction == Direction.INBOUND for r in reqs)
    # both messages were marked \Seen so they aren't re-ingested
    assert len(fake.stored) == 2
    # the mailbox row records the run
    assert mb.ingested_count == 2
    assert mb.last_error is None
    assert mb.last_result["ingested"] == 2


def test_poll_connect_failure_records_error(db):
    mb = _mailbox(db)

    def boom(_mb):
        raise OSError("connection refused")

    result = EP.poll_mailbox(db, mb, connect=boom)
    assert result["ok"] is False
    assert "connection refused" in result["error"]
    assert mb.last_error is not None

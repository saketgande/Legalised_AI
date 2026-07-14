"""The request-type catalog — what the front door accepts.

CONTRACT types run the full CLM engine (draft/redline -> approve -> sign ->
file -> track). ADVICE types run the lighter resolution engine (triage ->
assign -> governed answer). The requester never learns which engine ran.

The catalog is org-scoped and seeded idempotently at startup; new types can be
added per org without code changes (the ADVICE engine is generic).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import RequestCategory, RequestType

# key, label, description, category, default SLA hours, ordinal
DEFAULT_TYPES = [
    ("nda", "NDA / confidentiality",
     "Mutual or one-way NDA — drafted from the playbook or their paper redlined.",
     RequestCategory.CONTRACT, 8, 1),
    ("legal_question", "Legal question",
     "Ask the legal team anything — employment, IP, corporate, commercial.",
     RequestCategory.ADVICE, 24, 2),
    ("marketing_review", "Marketing / comms review",
     "Review a claim, campaign, landing page, or press release before it ships.",
     RequestCategory.ADVICE, 24, 3),
    ("vendor_review", "Vendor / procurement review",
     "Assess a new vendor's terms, security addendum, or order form.",
     RequestCategory.ADVICE, 48, 4),
    ("privacy_request", "Privacy / data request",
     "DSARs, data-sharing questions, processing assessments.",
     RequestCategory.ADVICE, 48, 5),
    ("other", "Something else",
     "Anything that doesn't fit the categories above — we'll triage it.",
     RequestCategory.ADVICE, 48, 6),
]


def ensure_default_request_types(db: Session, org_id: str) -> None:
    """Idempotent: adds any missing default type; never touches existing rows
    (an admin's edits to labels/SLAs survive restarts)."""
    existing = {
        t.key for t in db.execute(
            select(RequestType).where(RequestType.org_id == org_id)
        ).scalars().all()
    }
    for key, label, desc, category, sla, ordinal in DEFAULT_TYPES:
        if key not in existing:
            db.add(RequestType(
                org_id=org_id, key=key, label=label, description=desc,
                category=category, default_sla_hours=sla, ordinal=ordinal,
            ))


def list_types(db: Session, org_id: str, *, active_only: bool = True) -> list[RequestType]:
    stmt = select(RequestType).where(RequestType.org_id == org_id).order_by(RequestType.ordinal.asc())
    rows = db.execute(stmt).scalars().all()
    return [t for t in rows if t.active] if active_only else list(rows)


def get_type(db: Session, org_id: str, key: str) -> RequestType | None:
    return db.execute(
        select(RequestType).where(RequestType.org_id == org_id, RequestType.key == key)
    ).scalars().first()

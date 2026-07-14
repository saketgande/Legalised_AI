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
    ("dpa", "DPA / data processing",
     "Data processing agreement — drafted from our standard terms or their paper "
     "redlined against them. Always reviewed by a lawyer before it goes out.",
     RequestCategory.CONTRACT, 24, 2),
    ("legal_question", "Legal question",
     "Ask the legal team anything — employment, IP, corporate, commercial.",
     RequestCategory.ADVICE, 24, 3),
    ("marketing_review", "Marketing / comms review",
     "Review a claim, campaign, landing page, or press release before it ships.",
     RequestCategory.ADVICE, 24, 4),
    ("vendor_review", "Vendor / procurement review",
     "Assess a new vendor's terms, security addendum, or order form.",
     RequestCategory.ADVICE, 48, 5),
    ("privacy_request", "Privacy / data request",
     "DSARs, data-sharing questions, processing assessments.",
     RequestCategory.ADVICE, 48, 6),
    ("other", "Something else",
     "Anything that doesn't fit the categories above — we'll triage it.",
     RequestCategory.ADVICE, 48, 7),
]


BANDS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
VALID_RUNGS = ("vp_legal", "gc")

def default_risk_ladders(category: RequestCategory, key: str) -> dict:
    """The governance policy as data. The NDA wedge has earned an AUTO lane at
    LOW risk; every other contract type sees a lawyer at every band — the old
    hardcoded type gate, now a matrix row an admin can see (but the API refuses
    to blank: see validate_risk_ladders)."""
    if category != RequestCategory.CONTRACT:
        return {}
    if key == "nda":
        return {"LOW": [], "MEDIUM": ["vp_legal"],
                "HIGH": ["vp_legal", "gc"], "CRITICAL": ["vp_legal", "gc"]}
    return {"LOW": ["vp_legal"], "MEDIUM": ["vp_legal"],
            "HIGH": ["vp_legal", "gc"], "CRITICAL": ["vp_legal", "gc"]}


def validate_risk_ladders(matrix: dict, *, type_key: str, category: RequestCategory) -> list[str]:
    """Returns a list of problems (empty = valid). Guards the invariants that
    keep 'conservative governance' from being one admin edit away from gone:
    every band present, known rungs only, bands at MEDIUM+ never empty, and
    non-NDA contract types never auto-send even at LOW."""
    problems: list[str] = []
    if category != RequestCategory.CONTRACT:
        return ["risk ladders only apply to CONTRACT types"]
    for band in BANDS:
        rungs = matrix.get(band)
        if not isinstance(rungs, list):
            problems.append(f"band {band} missing or not a list")
            continue
        for rung in rungs:
            if rung not in VALID_RUNGS:
                problems.append(f"unknown rung '{rung}' in band {band}")
        if band != "LOW" and len(rungs) == 0:
            problems.append(f"band {band} cannot be empty — off-policy paper must see a human")
        if band == "LOW" and type_key != "nda" and len(rungs) == 0:
            problems.append("LOW cannot be empty for non-NDA contract types — they always see a lawyer")
    extra = set(matrix.keys()) - set(BANDS)
    if extra:
        problems.append(f"unknown bands: {sorted(extra)}")
    return problems


def risk_matrix_for(db: Session, org_id: str, type_key: str) -> dict:
    """The effective matrix for a type — stored row if present+valid, else the
    category default (so a legacy/blank row can never mean 'no governance')."""
    rt = get_type(db, org_id, (type_key or "nda").lower())
    if rt is None:
        return default_risk_ladders(RequestCategory.CONTRACT, (type_key or "nda").lower())
    stored = rt.risk_ladders or {}
    if stored and not validate_risk_ladders(stored, type_key=rt.key, category=rt.category):
        return stored
    return default_risk_ladders(rt.category, rt.key)


def ensure_default_request_types(db: Session, org_id: str) -> None:
    """Idempotent: adds any missing default type; never touches existing rows
    (an admin's edits to labels/SLAs survive restarts) — except backfilling a
    missing risk matrix, which existing rows predate."""
    rows = db.execute(
        select(RequestType).where(RequestType.org_id == org_id)
    ).scalars().all()
    existing = {t.key for t in rows}
    for key, label, desc, category, sla, ordinal in DEFAULT_TYPES:
        if key not in existing:
            db.add(RequestType(
                org_id=org_id, key=key, label=label, description=desc,
                category=category, default_sla_hours=sla, ordinal=ordinal,
                risk_ladders=default_risk_ladders(category, key),
            ))
    for t in rows:  # backfill pre-matrix rows
        if t.category == RequestCategory.CONTRACT and not t.risk_ladders:
            t.risk_ladders = default_risk_ladders(t.category, t.key)


def list_types(db: Session, org_id: str, *, active_only: bool = True) -> list[RequestType]:
    stmt = select(RequestType).where(RequestType.org_id == org_id).order_by(RequestType.ordinal.asc())
    rows = db.execute(stmt).scalars().all()
    return [t for t in rows if t.active] if active_only else list(rows)


def get_type(db: Session, org_id: str, key: str) -> RequestType | None:
    return db.execute(
        select(RequestType).where(RequestType.org_id == org_id, RequestType.key == key)
    ).scalars().first()

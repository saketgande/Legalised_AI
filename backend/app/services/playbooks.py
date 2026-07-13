"""Playbook resolution — the single source of truth for *which* playbook a
request is judged against.

An organisation can maintain several playbooks (a library): e.g. a standard NDA
position, a stricter vendor/procurement position, an M&A position. Exactly one
is the org **default** (``active=True``). A request either names a specific
playbook (``request.playbook_id``) or falls back to the default.

Both engines — outbound generation and inbound redline — resolve through here,
so rules are always scoped to one org + one playbook. (Before this existed the
inbound path loaded *every* rule in the database, ignoring both boundaries.)
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Playbook, PlaybookRule, Request


class PlaybookResolutionError(ValueError):
    """No usable playbook — either the named one doesn't belong to the org, or
    the org has no default. Routers translate this to a 400/404."""


def resolve_playbook(db: Session, org_id: str, playbook_id: str | None = None) -> Playbook:
    """A specific playbook when named (org-checked), else the org's default."""
    if playbook_id:
        pb = db.get(Playbook, playbook_id)
        if pb is None or pb.org_id != org_id:
            raise PlaybookResolutionError("playbook not found for organisation")
        return pb
    pb = db.execute(
        select(Playbook)
        .where(Playbook.org_id == org_id, Playbook.active == True)  # noqa: E712
        .order_by(Playbook.created_at.asc())
    ).scalars().first()
    if pb is None:
        raise PlaybookResolutionError("no active playbook for organisation")
    return pb


def load_rules(db: Session, playbook_id: str) -> list[PlaybookRule]:
    return db.execute(
        select(PlaybookRule)
        .where(PlaybookRule.playbook_id == playbook_id)
        .order_by(PlaybookRule.ordinal.asc())
    ).scalars().all()


def rule_applies(rule: PlaybookRule, request: Request) -> bool:
    """Within-playbook conditioning: a rule tagged for a specific NDA type only
    applies to that type (mutual vs one-way)."""
    applies = rule.applies_when or {}
    want = applies.get("ndaType")
    if want and want != request.nda_type.value:
        return False
    return True

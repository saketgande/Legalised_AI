"""The negotiation loop — the back-and-forth that real contracts live in.

    APPROVED --send_to_counterparty--> WITH_COUNTERPARTY
        --record_counterparty_return--> RETURNED
        --(re-segment -> re-redline -> re-score -> re-ladder)--> IN_REVIEW
        --approvals cleared--> APPROVED --> (another round | send for signature)

Every return bumps ``request.round`` and produces its own DocumentVersion,
ReviewRun, RiskAssessment, and approval ladder — the same governed cycle as
round 1, on the same ticket, on the same audit chain. Nothing about a later
round is less governed than the first.
"""
from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    ActorType,
    Clause,
    Counterparty,
    Document,
    DocumentVersion,
    Request,
    RequestState,
)
from .audit import record_audit
from .intake import Actor, finalize_round_governance
from .redline import classify, keyword_map_for, run_inbound_review, segment


class NegotiationError(Exception):
    """State-machine violation — the router translates to 409."""


def send_to_counterparty(db: Session, r: Request, actor: Actor) -> Request:
    """Send the approved paper to the counterparty for THEIR review (not for
    signature — that's the convergence path). What goes out is the current
    document version (outbound) or the approved counter-proposal (inbound)."""
    if r.state != RequestState.APPROVED:
        raise NegotiationError(f"request must be APPROVED to send to the counterparty (is {r.state.value})")

    cp = db.get(Counterparty, r.counterparty_id)
    doc = db.get(Document, r.document_id) if r.document_id else None
    version = db.get(DocumentVersion, doc.current_version_id) if doc and doc.current_version_id else None

    r.state = RequestState.WITH_COUNTERPARTY
    from .workflows import mark_stage

    mark_stage(db, r, "approvals", "done", round_no=r.round)
    mark_stage(db, r, "counterparty", "active", round_no=r.round)
    record_audit(
        db, org_id=r.org_id, action="request.sent_to_counterparty", resource_type="Request",
        resource_id=r.id, actor_id=actor.id, actor_type=actor.type, actor_label=actor.label,
        metadata={"round": r.round, "counterparty": cp.name if cp else None,
                  "document_version": version.version_no if version else None,
                  "content_hash": version.content_hash if version else None},
    )
    db.commit()
    db.refresh(r)
    return r


def _previous_clause_map(db: Session, doc: Document, before_version_id: str) -> dict[str, str]:
    """clause_type -> body of the version we last sent, for the changed-vs-ours diff."""
    prev = db.get(DocumentVersion, before_version_id) if before_version_id else None
    if prev is None:
        return {}
    clauses = db.execute(
        select(Clause).where(Clause.document_version_id == prev.id)
    ).scalars().all()
    return {c.clause_type: c.body_text for c in clauses if c.clause_type}


def record_counterparty_return(
    db: Session, r: Request, *, body_text: str, actor: Actor, source: str = "paste",
) -> Request:
    """Their markup came back. Spin the next round: new document version,
    fresh redline against the playbook, changed-vs-our-last-position diff,
    new risk score, rebuilt ladder — all on this ticket."""
    if r.state != RequestState.WITH_COUNTERPARTY:
        raise NegotiationError(
            f"request is not with the counterparty (is {r.state.value}) — nothing to return")
    body_text = (body_text or "").strip()
    if len(body_text) < 40:
        raise NegotiationError("the returned document text is too short to review")

    from .playbooks import load_rules, resolve_playbook

    r.round = (r.round or 1) + 1
    r.state = RequestState.RETURNED
    from .workflows import mark_stage

    mark_stage(db, r, "counterparty", "done", round_no=r.round - 1)  # their turn ended
    cp = db.get(Counterparty, r.counterparty_id)
    record_audit(
        db, org_id=r.org_id, action="request.counterparty_returned", resource_type="Request",
        resource_id=r.id, actor_id=actor.id, actor_type=actor.type, actor_label=actor.label,
        metadata={"round": r.round, "source": source, "counterparty": cp.name if cp else None,
                  "chars": len(body_text)},
    )

    # their markup becomes the next version of THIS request's document
    doc = db.get(Document, r.document_id)
    if doc is None:  # defensive: a contract request always has a document by APPROVED
        raise NegotiationError("request has no document to version")
    prev_version_id = doc.current_version_id
    prev_map = _previous_clause_map(db, doc, prev_version_id)
    last_no = db.execute(
        select(DocumentVersion.version_no).where(DocumentVersion.document_id == doc.id)
        .order_by(DocumentVersion.version_no.desc())
    ).scalars().first() or 0
    version = DocumentVersion(
        document_id=doc.id, version_no=last_no + 1, body_markdown=body_text,
        content_hash=hashlib.sha256(body_text.encode("utf-8")).hexdigest(),
        generated_by=f"counterparty-return-r{r.round}-{source}",
    )
    db.add(version)
    db.flush()

    tkey = (r.type or "nda").lower()
    playbook = resolve_playbook(db, r.org_id, r.playbook_id, contract_type=tkey)
    kmap = keyword_map_for(load_rules(db, playbook.id), include_base=(tkey == "nda"))
    changed = 0
    for i, (section_no, heading, body) in enumerate(segment(body_text), start=1):
        ctype = classify(heading, body, kmap)
        if ctype and ctype in prev_map and prev_map[ctype].strip() != body.strip():
            changed += 1
        db.add(Clause(
            document_version_id=version.id, ordinal=i, section_no=section_no or str(i),
            clause_type=ctype, heading=heading, body_text=body,
        ))
    doc.current_version_id = version.id
    db.flush()

    # fresh redline round against the playbook (same engine as round 1)
    run = run_inbound_review(db, r)
    summary = dict(run.summary or {})
    summary["changed_vs_previous"] = changed
    run.summary = summary
    record_audit(
        db, org_id=r.org_id, action="review.completed", resource_type="Request",
        resource_id=r.id, actor_type=ActorType.AGENT, actor_label="Redline Engine",
        metadata={"round": r.round, "summary": run.summary,
                  "proposed_changes": len(run.changes),
                  "changed_vs_our_last_position": changed, "source": source},
    )

    # fresh score, fresh ladder — round N is governed exactly like round 1
    finalize_round_governance(db, r, run=run)
    db.commit()
    db.refresh(r)
    return r

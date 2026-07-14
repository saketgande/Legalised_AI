"""Approval ladder assembly.

For the outbound skeleton the ladder is built from the triage blockers: each
blocker maps to the rung that owns it. In the inbound slice the same builder
will instead take the union of rungs triggered by found deviations — same shape,
different input.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ApprovalLadder, ApprovalStep, Lane, Request, StepStatus, User

# seniority order so the ladder is presented in a sensible sequence
_RUNG_ORDER = {"requesting_manager": 0, "vp_legal": 1, "gc": 2}


def _rung_for_reason(reason: str) -> str:
    r = reason.lower()
    if "jurisdiction" in r or "governing" in r:
        return "gc"
    if "term" in r or "cap" in r or "liability" in r:
        return "vp_legal"
    return "vp_legal"


def _assignee_for_rung(db: Session, org_id: str, rung: str) -> User | None:
    role = {"gc": "gc", "vp_legal": "vp_legal", "requesting_manager": "attorney"}.get(rung, "attorney")
    user = db.execute(
        select(User).where(User.org_id == org_id, User.role == role)
    ).scalars().first()
    if user is None:
        user = db.execute(select(User).where(User.org_id == org_id)).scalars().first()
    return user


def build_ladder(db: Session, request: Request, reasons: list[str]) -> ApprovalLadder:
    """Create a ladder from ASSISTED-lane reasons (deduped by rung)."""
    ladder = ApprovalLadder(request_id=request.id, status="PENDING")
    db.add(ladder)
    db.flush()

    seen: dict[str, str] = {}  # rung -> reason (first one wins for display)
    for reason in reasons:
        rung = _rung_for_reason(reason)
        seen.setdefault(rung, reason)

    for ordinal, (rung, reason) in enumerate(
        sorted(seen.items(), key=lambda kv: _RUNG_ORDER.get(kv[0], 9))
    ):
        assignee = _assignee_for_rung(db, request.org_id, rung)
        db.add(
            ApprovalStep(
                ladder_id=ladder.id,
                ordinal=ordinal,
                rung=rung,
                assignee_user_id=assignee.id if assignee else None,
                reason=reason,
                status=StepStatus.PENDING,
            )
        )
    db.flush()
    return ladder


def supersede_ladder(db: Session, request: Request) -> bool:
    """Retire the current ladder before rebuilding (a new round = new risk =
    new governance). Decided steps stay in history via the audit ledger; the
    rows themselves are replaced so exactly one ladder is ever open."""
    ladders = db.execute(
        select(ApprovalLadder).where(ApprovalLadder.request_id == request.id)
    ).scalars().all()
    if not ladders:
        return False
    for ladder in ladders:
        for s in list(ladder.steps):
            db.delete(s)
        db.delete(ladder)
    db.flush()
    return True


def build_ladder_from_risk(
    db: Session, request: Request, assessment, matrix: dict,
    extra_rungs: list[dict] | None = None,
) -> ApprovalLadder | None:
    """The score picks the ladder. ``matrix`` maps band -> ordered rung list
    (the per-type governance policy as data); ``extra_rungs`` lets workflow
    rules add steps ([{rung, reason}]). Returns None when the band's row is
    empty and nothing extra applies — the AUTO lane."""
    band = assessment.band.value if hasattr(assessment.band, "value") else str(assessment.band)
    rungs = list(matrix.get(band) or [])
    for extra in (extra_rungs or []):
        if extra.get("rung") not in rungs:
            rungs.append(extra["rung"])
    if not rungs:
        return None

    supersede_ladder(db, request)
    ladder = ApprovalLadder(request_id=request.id, status="PENDING")
    db.add(ladder)
    db.flush()

    # Step reasons: a workflow-gate rung keeps its own reason; every matrix-
    # picked rung gets the SAME honest summary — band, score, top drivers.
    # (Zipping ranked factors onto rungs one-by-one attributed the strongest
    # factor to the most junior rung, and that misattribution was being sealed
    # into the approval audit rows.)
    factor_labels = [f["label"] for f in sorted(
        (assessment.factors or []), key=lambda f: -int(f.get("points", 0))
    )]
    drivers = "; ".join(factor_labels[:2]) if factor_labels else "policy requires sign-off"
    band_reason = f"Risk {band} ({assessment.score}/100) — {drivers}"
    extra_by_rung = {e.get("rung"): e.get("reason", "") for e in (extra_rungs or [])}
    for ordinal, rung in enumerate(sorted(set(rungs), key=lambda x: _RUNG_ORDER.get(x, 9))):
        reason = extra_by_rung.get(rung) or band_reason
        assignee = _assignee_for_rung(db, request.org_id, rung)
        db.add(ApprovalStep(
            ladder_id=ladder.id, ordinal=ordinal, rung=rung,
            assignee_user_id=assignee.id if assignee else None,
            reason=reason, status=StepStatus.PENDING,
        ))
    db.flush()
    return ladder


def ladder_for_request(db: Session, request_id: str) -> ApprovalLadder | None:
    return db.execute(
        select(ApprovalLadder).where(ApprovalLadder.request_id == request_id)
    ).scalars().first()


def all_steps_cleared(ladder: ApprovalLadder) -> bool:
    return all(s.status == StepStatus.APPROVED for s in ladder.steps)


def approval_blockers(db: Session, request: Request) -> list[str]:
    """The single source of truth for 'may this request flip to APPROVED'.
    BOTH gates must clear — the risk-built ladder AND the current round's
    redline decisions. Two half-gates checked in two different endpoints is
    exactly how a CRITICAL matter slips past its GC rung."""
    from .redline import latest_run

    blockers: list[str] = []
    ladder = ladder_for_request(db, request.id)
    if ladder is not None and not all_steps_cleared(ladder):
        pending = [s.rung for s in ladder.steps if s.status == StepStatus.PENDING]
        blockers.append(f"approval ladder has pending steps: {', '.join(pending)}")
    run = latest_run(db, request.id)
    if run is not None and any(c.decision == "PENDING" for c in run.changes):
        n = sum(1 for c in run.changes if c.decision == "PENDING")
        blockers.append(f"{n} proposed redline{'s' if n != 1 else ''} still undecided")
    return blockers

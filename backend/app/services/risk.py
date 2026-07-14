"""AI risk score — the number that steers governance.

Every drafted or redlined round produces one ``RiskAssessment``:

* **Deterministic core.** Points from the round's findings (walk-away breaches,
  deviations priced by their playbook rung, missing mandatory clauses, novel
  clauses) plus request facts (off-policy jurisdiction / term / purpose,
  counterparty posture). Code decides these — never the model.
* **AI adjustment (optional).** Claude reads the round and may ADD up to
  +30 points with a note — it can raise severity it can never lower it, the
  same floor discipline as the redline post-checks. The heuristic client
  abstains, so the score is fully deterministic without an API key.

The resulting band (LOW / MEDIUM / HIGH / CRITICAL) is what the ladder matrix
(slice 2) maps to approval rungs, re-derived on every negotiation round.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    ActorType,
    Counterparty,
    Request,
    ReviewRun,
    RiskAssessment,
    RiskBand,
)
from .audit import record_audit

# band thresholds — monotone in score
_BANDS = [(70, RiskBand.CRITICAL), (40, RiskBand.HIGH), (15, RiskBand.MEDIUM), (0, RiskBand.LOW)]

# deterministic factor weights
W = {
    "walk_away": 70,          # per walk-away breach — CRITICAL on its own; the line we never cross
    "deviation_gc": 25,       # deviation whose playbook rung is gc
    "deviation_vp": 12,       # deviation priced at vp_legal
    "deviation_other": 8,
    "missing_mandatory": 7,   # per omitted mandatory clause
    "fallback": 4,            # acceptable fallback — priced, but not free
    "novel": 3,               # unreviewable clause a human must read
    "jurisdiction": 40,       # off-policy governing law (was a GC rung pre-scoring)
    "term": 20,               # term over the self-serve cap
    "purpose": 20,            # purpose not pre-approved
    "counterparty_flag": 75,  # blocklisted / sanctioned — a true CRITICAL floor
    "their_paper": 5,         # inbound paper carries baseline risk vs our own
}
AI_ADJUSTMENT_CAP = 30


def band_for(score: int) -> RiskBand:
    for floor, band in _BANDS:
        if score >= floor:
            return band
    return RiskBand.LOW


def _fact_factors(db: Session, request: Request) -> list[dict]:
    """Request-fact factors — apply to every round, both directions."""
    factors: list[dict] = []
    cp = db.get(Counterparty, request.counterparty_id)
    if cp is not None and (cp.sanctioned or cp.blocklisted):
        factors.append({
            "label": f"counterparty is {'sanctioned' if cp.sanctioned else 'blocklisted'} — hard escalation",
            "points": W["counterparty_flag"], "kind": "DETERMINISTIC",
        })
    if request.jurisdiction not in settings.auto_allowed_jurisdictions:
        factors.append({
            "label": f"governing law '{request.jurisdiction}' is outside the approved set",
            "points": W["jurisdiction"], "kind": "DETERMINISTIC",
        })
    if request.term_months > settings.auto_max_term_months:
        factors.append({
            "label": f"term {request.term_months}mo exceeds the {settings.auto_max_term_months}mo self-serve cap",
            "points": W["term"], "kind": "DETERMINISTIC",
        })
    if request.purpose not in settings.auto_allowed_purposes:
        factors.append({
            "label": f"purpose '{request.purpose}' is not pre-approved",
            "points": W["purpose"], "kind": "DETERMINISTIC",
        })
    return factors


def _finding_factors(run: ReviewRun) -> list[dict]:
    """Factors from a redline round's findings."""
    factors: list[dict] = []
    for c in run.changes:
        if c.finding == "DEVIATION":
            is_walk_away = any(
                ch.get("name") == "position_ladder" and str(ch.get("detail", "")).startswith("walk_away")
                for ch in (c.checks or [])
            )
            if is_walk_away:
                factors.append({
                    "label": f"WALK-AWAY breach — {c.heading}",
                    "points": W["walk_away"], "kind": "DETERMINISTIC",
                })
            elif c.triggered_rung == "gc":
                factors.append({
                    "label": f"deviation (GC-priced) — {c.heading}",
                    "points": W["deviation_gc"], "kind": "DETERMINISTIC",
                })
            elif c.triggered_rung == "vp_legal":
                factors.append({
                    "label": f"deviation — {c.heading}",
                    "points": W["deviation_vp"], "kind": "DETERMINISTIC",
                })
            else:
                factors.append({
                    "label": f"deviation — {c.heading}",
                    "points": W["deviation_other"], "kind": "DETERMINISTIC",
                })
        elif c.finding == "MISSING":
            factors.append({
                "label": f"mandatory clause missing — {c.heading}",
                "points": W["missing_mandatory"], "kind": "DETERMINISTIC",
            })
        elif c.finding == "ACCEPTABLE_FALLBACK":
            factors.append({
                "label": f"fallback position accepted — {c.heading}",
                "points": W["fallback"], "kind": "DETERMINISTIC",
            })
        elif c.finding == "NOVEL":
            factors.append({
                "label": f"novel clause (no playbook position) — {c.heading}",
                "points": W["novel"], "kind": "DETERMINISTIC",
            })
    return factors


def _ai_pass(ai, request: Request, run: ReviewRun | None, det_score: int) -> tuple[int, str, str]:
    """(added_points, note, model). Floor rule enforced HERE, not trusted from
    the client: negative or absent adjustments read as 0."""
    if ai is None:
        return 0, "", "deterministic"
    try:
        verdict = ai.assess_risk(request, run, det_score)
    except Exception:
        return 0, "", "deterministic"
    if verdict is None:
        return 0, "", "deterministic"
    added = max(0, min(AI_ADJUSTMENT_CAP, int(verdict.get("added_points", 0) or 0)))
    note = str(verdict.get("note", "")).strip()[:300]
    return added, note, str(verdict.get("model", "ai"))


def assess_round(
    db: Session, request: Request, *, run: ReviewRun | None = None,
    round_no: int | None = None, ai=None, extra_factors: list[dict] | None = None,
) -> RiskAssessment:
    """Score one round. ``run`` present = redline round (findings drive the
    score); absent = our own freshly-assembled paper (facts only, on-playbook by
    construction). ``extra_factors`` lets callers price in context the engine
    can't see (a routing rule that escalated, a workflow-rule gate). Idempotent
    per (request, round): re-scoring replaces."""
    from .ai import get_ai_client

    ai = ai if ai is not None else get_ai_client()
    rnd = round_no or getattr(request, "round", 1) or 1

    factors = _fact_factors(db, request) + list(extra_factors or [])
    if run is not None:
        factors = _finding_factors(run) + factors
        factors.append({"label": "counterparty paper under review", "points": W["their_paper"],
                        "kind": "DETERMINISTIC"})
    det_score = min(100, sum(f["points"] for f in factors))

    added, note, model = _ai_pass(ai, request, run, det_score)
    if added > 0:
        factors.append({"label": f"AI risk adjustment — {note or 'model raised severity'}",
                        "points": added, "kind": "AI"})
    score = min(100, det_score + added)

    existing = db.execute(
        select(RiskAssessment).where(
            RiskAssessment.request_id == request.id, RiskAssessment.round == rnd
        )
    ).scalars().first()
    if existing is not None:
        db.delete(existing)
        db.flush()

    assessment = RiskAssessment(
        request_id=request.id, round=rnd, review_run_id=run.id if run else None,
        score=score, band=band_for(score), factors=factors,
        ai_adjustment=added, ai_note=note, model=model if added > 0 else "deterministic",
    )
    db.add(assessment)
    db.flush()
    record_audit(
        db, org_id=request.org_id, action="risk.scored", resource_type="Request",
        resource_id=request.id, actor_type=ActorType.AGENT, actor_label="Risk Engine",
        metadata={"round": rnd, "score": score, "band": assessment.band.value,
                  "deterministic": det_score, "ai_adjustment": added,
                  "factors": [f["label"] for f in factors][:12]},
    )
    return assessment


def latest_assessment(db: Session, request_id: str) -> RiskAssessment | None:
    return db.execute(
        select(RiskAssessment)
        .where(RiskAssessment.request_id == request_id)
        .order_by(RiskAssessment.round.desc())
    ).scalars().first()


def assessment_history(db: Session, request_id: str) -> list[RiskAssessment]:
    return list(db.execute(
        select(RiskAssessment)
        .where(RiskAssessment.request_id == request_id)
        .order_by(RiskAssessment.round.asc())
    ).scalars().all())

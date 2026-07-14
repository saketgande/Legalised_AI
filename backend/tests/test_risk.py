"""Risk engine regressions: deterministic factor scoring, band boundaries, the
AI raise-only floor, matrix-driven ladders, and the governance invariants
(non-NDA never auto, inbound never auto, escalation prices in)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    Counterparty,
    Direction,
    Organization,
    Person,
    Request,
    RequestCategory,
    RequestState,
    RequestType,
    ReviewRun,
    ProposedChange,
    RiskBand,
    DocumentVersion,
    Document,
)
from app.services.risk import assess_round, band_for, W
from app.services.request_types import (
    default_risk_ladders,
    risk_matrix_for,
    validate_risk_ladders,
)
from app.services.approvals import build_ladder_from_risk


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _setup(db, *, jurisdiction="US", term=12, purpose="sales_evaluation", type_="nda",
           sanctioned=False):
    org = Organization(name="T"); db.add(org); db.flush()
    p = Person(org_id=org.id, name="Req", email="r@t.example"); db.add(p)
    cp = Counterparty(org_id=org.id, name="CP", sanctioned=sanctioned); db.add(cp)
    db.flush()
    r = Request(ref=f"REQ-T-{jurisdiction}-{term}", org_id=org.id, type=type_,
                direction=Direction.OUTBOUND, state=RequestState.NEW,
                requester_id=p.id, counterparty_id=cp.id,
                purpose=purpose, jurisdiction=jurisdiction, term_months=term)
    db.add(r); db.flush()
    return org, r


class AbstainAI:
    def assess_risk(self, request, run, det): return None


class RogueAI:
    """Tries to LOWER the score — the floor must clamp it to zero."""
    def assess_risk(self, request, run, det):
        return {"added_points": -50, "note": "all fine, trust me", "model": "rogue"}


class RaisingAI:
    def assess_risk(self, request, run, det):
        return {"added_points": 99, "note": "unusual combination", "model": "raiser"}


# ————————————————— deterministic scoring —————————————————
def test_in_policy_outbound_is_low(db):
    org, r = _setup(db)
    a = assess_round(db, r, ai=AbstainAI())
    assert a.score < 15 and a.band == RiskBand.LOW


def test_off_policy_facts_stack(db):
    org, r = _setup(db, jurisdiction="UK", term=36)
    a = assess_round(db, r, ai=AbstainAI())
    assert a.score == W["jurisdiction"] + W["term"]
    assert a.band == RiskBand.HIGH  # 60


def test_sanctioned_counterparty_is_critical_floor(db):
    org, r = _setup(db, sanctioned=True, jurisdiction="UK")
    a = assess_round(db, r, ai=AbstainAI())
    assert a.band == RiskBand.CRITICAL


def test_band_boundaries():
    assert band_for(0) == RiskBand.LOW
    assert band_for(14) == RiskBand.LOW
    assert band_for(15) == RiskBand.MEDIUM
    assert band_for(39) == RiskBand.MEDIUM
    assert band_for(40) == RiskBand.HIGH
    assert band_for(69) == RiskBand.HIGH
    assert band_for(70) == RiskBand.CRITICAL
    assert band_for(100) == RiskBand.CRITICAL


# ————————————————— the AI floor —————————————————
def test_rogue_ai_cannot_lower_the_score(db):
    org, r = _setup(db, jurisdiction="UK")
    a = assess_round(db, r, ai=RogueAI())
    assert a.score == W["jurisdiction"]  # -50 clamped to 0
    assert a.ai_adjustment == 0


def test_ai_addition_is_capped(db):
    org, r = _setup(db)
    a = assess_round(db, r, ai=RaisingAI())
    assert a.ai_adjustment == 30  # 99 clamped to the cap
    assert any(f["kind"] == "AI" for f in a.factors)


# ————————————————— findings drive redline rounds —————————————————
def _run_with(db, r, findings):
    doc = Document(org_id=r.org_id, request_id=r.id, title="t"); db.add(doc); db.flush()
    v = DocumentVersion(document_id=doc.id, body_markdown="x", content_hash="h")
    db.add(v); db.flush()
    run = ReviewRun(request_id=r.id, document_version_id=v.id); db.add(run); db.flush()
    for i, (finding, rung, checks) in enumerate(findings):
        db.add(ProposedChange(run_id=run.id, ordinal=i, heading=f"C{i}", finding=finding,
                              triggered_rung=rung, checks=checks))
    db.flush()
    db.refresh(run)
    return run


def test_walk_away_breach_scores_critical(db):
    org, r = _setup(db)
    run = _run_with(db, r, [
        ("DEVIATION", "gc", [{"name": "position_ladder", "detail": "walk_away: crosses the line"}]),
        ("MISSING", "vp_legal", []),
        ("MISSING", "vp_legal", []),
        ("MISSING", "vp_legal", []),
    ])
    a = assess_round(db, r, run=run, ai=AbstainAI())
    # 45 walk-away + 3*7 missing + 5 their-paper = 71
    assert a.score >= 70 and a.band == RiskBand.CRITICAL


def test_fallbacks_price_cheap(db):
    org, r = _setup(db)
    run = _run_with(db, r, [("ACCEPTABLE_FALLBACK", "vp_legal", [])])
    a = assess_round(db, r, run=run, ai=AbstainAI())
    assert a.score == W["fallback"] + W["their_paper"]
    assert a.band == RiskBand.LOW


# ————————————————— matrix → ladder —————————————————
def test_default_matrices_shape():
    nda = default_risk_ladders(RequestCategory.CONTRACT, "nda")
    dpa = default_risk_ladders(RequestCategory.CONTRACT, "dpa")
    assert nda["LOW"] == [] and dpa["LOW"] == ["vp_legal"]
    assert validate_risk_ladders(nda, type_key="nda", category=RequestCategory.CONTRACT) == []
    assert validate_risk_ladders(dpa, type_key="dpa", category=RequestCategory.CONTRACT) == []


def test_validation_rejects_blank_governance():
    bad = {"LOW": [], "MEDIUM": [], "HIGH": ["vp_legal"], "CRITICAL": ["gc"]}
    probs = validate_risk_ladders(bad, type_key="nda", category=RequestCategory.CONTRACT)
    assert any("MEDIUM" in p for p in probs)
    probs = validate_risk_ladders(
        {"LOW": [], "MEDIUM": ["vp_legal"], "HIGH": ["vp_legal"], "CRITICAL": ["gc"]},
        type_key="dpa", category=RequestCategory.CONTRACT)
    assert any("non-NDA" in p for p in probs)


def test_ladder_from_band(db):
    org, r = _setup(db, jurisdiction="UK", term=36)  # HIGH
    a = assess_round(db, r, ai=AbstainAI())
    matrix = default_risk_ladders(RequestCategory.CONTRACT, "nda")
    ladder = build_ladder_from_risk(db, r, a, matrix)
    assert [s.rung for s in ladder.steps] == ["vp_legal", "gc"]
    assert all(s.reason for s in ladder.steps)


def test_low_band_nda_means_no_ladder(db):
    org, r = _setup(db)
    a = assess_round(db, r, ai=AbstainAI())
    matrix = default_risk_ladders(RequestCategory.CONTRACT, "nda")
    assert build_ladder_from_risk(db, r, a, matrix) is None  # AUTO lane


def test_low_band_dpa_still_ladders(db):
    org, r = _setup(db, type_="dpa")
    a = assess_round(db, r, ai=AbstainAI())
    matrix = default_risk_ladders(RequestCategory.CONTRACT, "dpa")
    ladder = build_ladder_from_risk(db, r, a, matrix)
    assert ladder is not None and [s.rung for s in ladder.steps] == ["vp_legal"]


def test_rebuild_supersedes_old_ladder(db):
    from app.models import ApprovalLadder
    from sqlalchemy import select

    org, r = _setup(db, jurisdiction="UK")
    a = assess_round(db, r, ai=AbstainAI())
    matrix = default_risk_ladders(RequestCategory.CONTRACT, "nda")
    build_ladder_from_risk(db, r, a, matrix)
    build_ladder_from_risk(db, r, a, matrix)  # round 2 rebuild
    ladders = db.execute(select(ApprovalLadder).where(ApprovalLadder.request_id == r.id)).scalars().all()
    assert len(ladders) == 1


def test_matrix_fallback_when_type_row_missing(db):
    org, r = _setup(db)
    # no RequestType rows at all -> category default, never "no governance"
    m = risk_matrix_for(db, org.id, "dpa")
    assert m["LOW"] == ["vp_legal"]


def test_rescore_same_round_replaces(db):
    org, r = _setup(db, jurisdiction="UK")
    a1 = assess_round(db, r, ai=AbstainAI())
    a2 = assess_round(db, r, ai=AbstainAI())
    from sqlalchemy import select
    from app.models import RiskAssessment
    rows = db.execute(select(RiskAssessment).where(RiskAssessment.request_id == r.id)).scalars().all()
    assert len(rows) == 1 and rows[0].id == a2.id

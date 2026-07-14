"""Negotiation-loop regressions: state machine, round bumps, per-round review
+ risk + rebuilt ladder, the changed-vs-our-last-position diff, and email
thread-matching a return into the same ticket."""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    ActorType,
    ApprovalLadder,
    Organization,
    Person,
    Playbook,
    PlaybookRule,
    Request,
    RequestState,
    ReviewRun,
    RiskAssessment,
    StepStatus,
)
from app.services.intake import Actor, create_outbound
from app.services.negotiation import (
    NegotiationError,
    record_counterparty_return,
    send_to_counterparty,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _org_with_playbook(db):
    org = Organization(name="T"); db.add(org); db.flush()
    pb = Playbook(org_id=org.id, name="Std", version=1, active=True); db.add(pb); db.flush()
    db.add_all([
        PlaybookRule(playbook_id=pb.id, rule_key="TERM-01", clause_type="term", heading="Term",
                     preferred_body="This Agreement lasts {{hold.term_months}} months.",
                     ordinal=1, mandatory=True, deviation_rung="vp_legal"),
        PlaybookRule(playbook_id=pb.id, rule_key="GOV-01", clause_type="governing_law",
                     heading="Governing Law",
                     preferred_body="Governed by the laws of the State of Delaware.",
                     ordinal=2, mandatory=True, deviation_rung="gc"),
    ])
    p = Person(org_id=org.id, name="Req", email="req@t.example"); db.add(p); db.flush()
    return org, p


def _approved_outbound(db, org, person):
    r = create_outbound(
        db, org=org.id, requester=person,
        actor=Actor(None, ActorType.SYSTEM, "t"),
        counterparty_name="Acme", nda_type="MUTUAL", purpose="sales_evaluation",
        jurisdiction="US", term_months=12,
    )
    assert r.state == RequestState.APPROVED  # in-policy NDA -> LOW -> AUTO
    return r


ACTOR = Actor(None, ActorType.USER, "Reviewer")

RETURN_TEXT = """1. Term
This Agreement shall remain in effect for sixty (60) months from the Effective Date.

2. Governing Law
This Agreement shall be governed by the laws of England and Wales.
"""


def test_full_loop_round_two(db):
    org, p = _org_with_playbook(db)
    r = _approved_outbound(db, org, p)

    r = send_to_counterparty(db, r, ACTOR)
    assert r.state == RequestState.WITH_COUNTERPARTY and r.round == 1

    r = record_counterparty_return(db, r, body_text=RETURN_TEXT, actor=ACTOR, source="paste")
    assert r.round == 2
    assert r.state == RequestState.IN_REVIEW  # off-playbook markup -> ladder -> review

    # round-2 artifacts exist: review run, risk assessment, fresh ladder
    runs = db.execute(select(ReviewRun).where(ReviewRun.request_id == r.id)).scalars().all()
    assert [x.round for x in runs] == [2]
    risks = db.execute(select(RiskAssessment).where(RiskAssessment.request_id == r.id)
                       .order_by(RiskAssessment.round)).scalars().all()
    assert [a.round for a in risks] == [1, 2]
    assert risks[1].score > risks[0].score  # their aggressive markup raised risk

    ladders = db.execute(select(ApprovalLadder).where(ApprovalLadder.request_id == r.id)).scalars().all()
    assert len(ladders) == 1 and all(s.status == StepStatus.PENDING for s in ladders[0].steps)


def test_changed_vs_previous_diff(db):
    org, p = _org_with_playbook(db)
    r = _approved_outbound(db, org, p)
    r = send_to_counterparty(db, r, ACTOR)
    r = record_counterparty_return(db, r, body_text=RETURN_TEXT, actor=ACTOR)
    run = db.execute(select(ReviewRun).where(ReviewRun.request_id == r.id)).scalars().first()
    # both clauses differ from what we sent (term + governing law)
    assert run.summary.get("changed_vs_previous", 0) >= 2


def test_return_requires_with_counterparty_state(db):
    org, p = _org_with_playbook(db)
    r = _approved_outbound(db, org, p)
    with pytest.raises(NegotiationError):
        record_counterparty_return(db, r, body_text=RETURN_TEXT, actor=ACTOR)


def test_send_requires_approved_state(db):
    org, p = _org_with_playbook(db)
    r = _approved_outbound(db, org, p)
    r = send_to_counterparty(db, r, ACTOR)
    with pytest.raises(NegotiationError):
        send_to_counterparty(db, r, ACTOR)  # already with them


def test_short_garbage_return_rejected(db):
    org, p = _org_with_playbook(db)
    r = _approved_outbound(db, org, p)
    r = send_to_counterparty(db, r, ACTOR)
    with pytest.raises(NegotiationError):
        record_counterparty_return(db, r, body_text="thanks, looks fine!", actor=ACTOR)
    assert r.round == 1  # nothing advanced


def test_email_thread_match_routes_into_loop(db):
    from app.services.email_intake import ingest_email

    org, p = _org_with_playbook(db)
    r = _approved_outbound(db, org, p)
    r = send_to_counterparty(db, r, ACTOR)

    res = ingest_email(
        db, org=org.id, from_email="legal@acme.example", from_name="Acme Legal",
        subject=f"RE: {r.ref} — our comments", body=RETURN_TEXT,
    )
    assert res.classified == "counterparty_return" and res.ref == r.ref
    db.refresh(r)
    assert r.round == 2 and r.state == RequestState.IN_REVIEW


def test_email_without_ref_still_normal_intake(db):
    from app.services.email_intake import ingest_email

    org, p = _org_with_playbook(db)
    r = _approved_outbound(db, org, p)
    send_to_counterparty(db, r, ACTOR)

    res = ingest_email(
        db, org=org.id, from_email="someone@corp.example",
        subject="Need an NDA with Globex",
        body="Please set up a mutual NDA with Globex Corp for sales evaluation, 12 months, US law.",
    )
    assert res.classified == "outbound"  # a NEW ticket, not a hijacked return

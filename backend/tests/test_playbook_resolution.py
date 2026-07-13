"""Multi-playbook resolution: the engine must scope rules to one org + one
playbook (specific-if-named, else the org default), and honor per-NDA-type
conditioning. Locks in the fix for the inbound bug that loaded every rule in the
database regardless of org or playbook.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    Direction,
    NdaType,
    Organization,
    Playbook,
    PlaybookRule,
    Request,
    RequestState,
)
from app.services.playbooks import (
    PlaybookResolutionError,
    load_rules,
    resolve_playbook,
    rule_applies,
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


def _pb(db, org_id, name, active):
    pb = Playbook(org_id=org_id, name=name, version=1, active=active)
    db.add(pb)
    db.flush()
    return pb


def _req(db, org_id, playbook_id=None, nda_type=NdaType.MUTUAL):
    r = Request(
        ref="REQ-TEST", org_id=org_id, direction=Direction.INBOUND, nda_type=nda_type,
        state=RequestState.NEW, requester_id="p1", counterparty_id="c1", purpose="x",
        playbook_id=playbook_id,
    )
    db.add(r)
    db.flush()
    return r


# ————————————————————— rule_applies (pure) —————————————————————
def test_rule_applies_untagged_matches_any():
    rule = PlaybookRule(rule_key="A", clause_type="x", heading="X", preferred_body="b", applies_when={})
    for t in (NdaType.MUTUAL, NdaType.ONE_WAY):
        req = Request(nda_type=t)
        assert rule_applies(rule, req) is True


def test_rule_applies_tagged_matches_only_that_type():
    rule = PlaybookRule(rule_key="A", clause_type="x", heading="X", preferred_body="b",
                        applies_when={"ndaType": "MUTUAL"})
    assert rule_applies(rule, Request(nda_type=NdaType.MUTUAL)) is True
    assert rule_applies(rule, Request(nda_type=NdaType.ONE_WAY)) is False


# ————————————————————— resolve_playbook (DB) —————————————————————
def test_resolve_default_picks_active(db):
    org = Organization(name="A"); db.add(org); db.flush()
    _pb(db, org.id, "Inactive", active=False)
    active = _pb(db, org.id, "Default", active=True)
    assert resolve_playbook(db, org.id).id == active.id


def test_resolve_named_returns_that_playbook(db):
    org = Organization(name="A"); db.add(org); db.flush()
    _pb(db, org.id, "Default", active=True)
    strict = _pb(db, org.id, "Strict", active=False)
    assert resolve_playbook(db, org.id, strict.id).id == strict.id


def test_resolve_rejects_other_orgs_playbook(db):
    """Org-scoping: a playbook id from another org must NOT resolve — this is the
    cross-tenant leak the old inbound path had."""
    a = Organization(name="A"); b = Organization(name="B"); db.add_all([a, b]); db.flush()
    _pb(db, a.id, "A default", active=True)
    b_pb = _pb(db, b.id, "B default", active=True)
    with pytest.raises(PlaybookResolutionError):
        resolve_playbook(db, a.id, b_pb.id)


def test_resolve_raises_when_no_active(db):
    org = Organization(name="A"); db.add(org); db.flush()
    _pb(db, org.id, "Inactive", active=False)
    with pytest.raises(PlaybookResolutionError):
        resolve_playbook(db, org.id)


def test_load_rules_scoped_to_one_playbook(db):
    """The bug: rules must come only from the requested playbook, never all of them."""
    org = Organization(name="A"); db.add(org); db.flush()
    p1 = _pb(db, org.id, "P1", active=True)
    p2 = _pb(db, org.id, "P2", active=False)
    db.add_all([
        PlaybookRule(playbook_id=p1.id, rule_key="P1-1", clause_type="term", heading="T", preferred_body="b", ordinal=1),
        PlaybookRule(playbook_id=p2.id, rule_key="P2-1", clause_type="term", heading="T", preferred_body="b", ordinal=1),
        PlaybookRule(playbook_id=p2.id, rule_key="P2-2", clause_type="purpose", heading="P", preferred_body="b", ordinal=2),
    ])
    db.flush()
    keys1 = {r.rule_key for r in load_rules(db, p1.id)}
    keys2 = {r.rule_key for r in load_rules(db, p2.id)}
    assert keys1 == {"P1-1"}
    assert keys2 == {"P2-1", "P2-2"}

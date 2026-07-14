"""Phase 2 regressions: type-scoped playbook resolution, the NDA-policy
scoping of the heuristic checks, contract-type detection for the pickerless
channels, and the advice/contract engine boundary."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Organization, Playbook, RequestCategory, RequestType
from app.services.ai import HeuristicAIClient
from app.services.intake import create_advice, detect_contract_type, Actor
from app.services.playbooks import PlaybookResolutionError, resolve_playbook
from app.models import ActorType


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _pb(db, org_id, name, active, ctype="nda"):
    pb = Playbook(org_id=org_id, name=name, version=1, active=active, contract_type_key=ctype)
    db.add(pb)
    db.flush()
    return pb


# ————————————————————— type-scoped resolution —————————————————————
def test_defaults_coexist_per_type(db):
    org = Organization(name="A"); db.add(org); db.flush()
    nda = _pb(db, org.id, "NDA book", active=True, ctype="nda")
    dpa = _pb(db, org.id, "DPA book", active=True, ctype="dpa")
    assert resolve_playbook(db, org.id, contract_type="nda").id == nda.id
    assert resolve_playbook(db, org.id, contract_type="dpa").id == dpa.id


def test_named_book_of_wrong_type_rejected(db):
    """A DPA request must never be drafted/redlined against an NDA book."""
    org = Organization(name="A"); db.add(org); db.flush()
    nda = _pb(db, org.id, "NDA book", active=True, ctype="nda")
    with pytest.raises(PlaybookResolutionError):
        resolve_playbook(db, org.id, nda.id, contract_type="dpa")


def test_admin_untyped_named_lookup_still_works(db):
    """The admin passes contract_type=None — named books resolve regardless of type."""
    org = Organization(name="A"); db.add(org); db.flush()
    dpa = _pb(db, org.id, "DPA book", active=False, ctype="dpa")
    assert resolve_playbook(db, org.id, dpa.id).id == dpa.id


def test_no_active_book_of_type_raises(db):
    org = Organization(name="A"); db.add(org); db.flush()
    _pb(db, org.id, "NDA book", active=True, ctype="nda")
    with pytest.raises(PlaybookResolutionError):
        resolve_playbook(db, org.id, contract_type="dpa")


def test_one_active_default_per_type_enforced_by_schema(db):
    """The partial unique index backs the invariant the activate endpoint
    maintains — a second active book of the same type must not persist."""
    from sqlalchemy.exc import IntegrityError

    org = Organization(name="A"); db.add(org); db.flush()
    _pb(db, org.id, "DPA book 1", active=True, ctype="dpa")
    with pytest.raises(IntegrityError):
        _pb(db, org.id, "DPA book 2", active=True, ctype="dpa")
        db.commit()


# ————————————————————— NDA policy stays NDA-scoped —————————————————————
def test_heuristic_liability_check_abstains_for_dpa():
    """The carve-out demand is NDA policy; a DPA whose preferred position is
    uncapped liability must not be judged by it."""
    class R:
        clause_type = "limitation_of_liability"
        fallbacks: list = []
        walk_away_text = ""

    clause = "Liability is capped at fees paid, no carve out."
    assert HeuristicAIClient().compare_clause(clause, R(), {}, contract_type="dpa") is None
    v = HeuristicAIClient().compare_clause(clause, R(), {}, contract_type="nda")
    assert v is not None and v.matches is False


# ————————————————————— pickerless-channel type detection —————————————————————
def test_detect_contract_type():
    assert detect_contract_type("We need a DPA with CloudVendor") == "dpa"
    assert detect_contract_type("please send the data processing agreement") == "dpa"
    assert detect_contract_type("Need an NDA with Umbrella Corp") == "nda"
    # 'dpa' must match as a word, not a substring
    assert detect_contract_type("the grandpa clause updates") == "nda"


# ————————————————————— engine boundary —————————————————————
def test_advice_rejects_contract_types(db):
    """A contract type filed through the advice engine would be a zombie —
    no document, no ladder, no resolution path."""
    org = Organization(name="A"); db.add(org); db.flush()
    db.add(RequestType(org_id=org.id, key="dpa", label="DPA / data processing",
                       description="", category=RequestCategory.CONTRACT,
                       default_sla_hours=24, ordinal=2, active=True))
    db.flush()
    with pytest.raises(ValueError):
        create_advice(
            db, org=org.id, requester=None,
            actor=Actor(id=None, type=ActorType.USER, label="t"),
            type_key="dpa", question="set one up?",
        )

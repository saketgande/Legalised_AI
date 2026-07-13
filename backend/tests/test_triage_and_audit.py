"""Unit tests for the two load-bearing pure-logic pieces:
the triage fork and the audit-chain hashing. No DB required.

Run: `pytest` from the backend directory (with the venv active).
"""
from types import SimpleNamespace

from app.models import Direction, Lane, NdaType, OurRole
from app.services import audit
from app.services.triage import triage_outbound


def _request(purpose="sales_evaluation", jurisdiction="US", term=24):
    return SimpleNamespace(
        direction=Direction.OUTBOUND,
        nda_type=NdaType.MUTUAL,
        our_role=OurRole.BOTH,
        purpose=purpose,
        jurisdiction=jurisdiction,
        term_months=term,
    )


def _cp(sanctioned=False, blocklisted=False):
    return SimpleNamespace(sanctioned=sanctioned, blocklisted=blocklisted)


def test_clean_request_takes_auto_lane():
    result = triage_outbound(_request(), _cp())
    assert result.lane == Lane.AUTO
    assert any("pre-approved" in r for r in result.reasons)


def test_long_term_forces_assisted():
    result = triage_outbound(_request(term=36), _cp())
    assert result.lane == Lane.ASSISTED
    assert any("exceeds" in r for r in result.reasons)


def test_foreign_jurisdiction_forces_assisted():
    result = triage_outbound(_request(jurisdiction="EU-DE"), _cp())
    assert result.lane == Lane.ASSISTED


def test_sanctioned_counterparty_escalates():
    result = triage_outbound(_request(), _cp(sanctioned=True))
    assert result.lane == Lane.ESCALATED


def test_audit_canonical_hash_is_deterministic():
    kwargs = dict(
        chain_position=1,
        prev_hash=audit.GENESIS,
        action="request.created",
        resource_type="Request",
        resource_id="abc",
        actor_id=None,
        actor_type="USER",
        metadata={"b": 2, "a": 1},
    )
    a = audit._canonical(**kwargs)
    b = audit._canonical(**kwargs)
    assert a == b
    # key order in metadata must not change the canonical form
    kwargs2 = dict(kwargs, metadata={"a": 1, "b": 2})
    assert audit._canonical(**kwargs2) == a


def test_audit_hash_changes_when_content_changes():
    base = dict(
        chain_position=1, prev_hash=audit.GENESIS, action="x",
        resource_type="Request", resource_id="1", actor_id=None,
        actor_type="SYSTEM", metadata={},
    )
    h1 = audit._hash(audit._canonical(**base))
    tampered = audit._hash(audit._canonical(**dict(base, resource_id="2")))
    assert h1 != tampered

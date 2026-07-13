"""Tests for playbook-manage permission grants + rule input validation."""
import pytest
from fastapi import HTTPException

from app.permissions import Permission, can
from app.routers.playbook import RuleIn, _validate


def test_playbook_manage_grants():
    for role in ("admin", "gc", "legal_ops"):
        assert can(role, Permission.PLAYBOOK_MANAGE), role
    for role in ("attorney", "vp_legal", "paralegal", "requester", "viewer"):
        assert not can(role, Permission.PLAYBOOK_MANAGE), role


def test_admin_still_superset():
    from app.permissions import ROLE_PERMISSIONS
    assert ROLE_PERMISSIONS["admin"] == set(Permission)  # new perm must be in the superuser bundle


def _rule(**kw):
    base = dict(rule_key="X-01", clause_type="x", heading="X", preferred_body="body")
    base.update(kw)
    return RuleIn(**base)


def test_validate_accepts_good_rule():
    _validate(_rule(deviation_rung="gc", nda_type="MUTUAL"))  # no raise


def test_validate_rejects_bad_rung():
    with pytest.raises(HTTPException):
        _validate(_rule(deviation_rung="ceo"))


def test_validate_rejects_bad_nda_type():
    with pytest.raises(HTTPException):
        _validate(_rule(nda_type="BILATERAL"))


def test_validate_requires_key_and_heading():
    with pytest.raises(HTTPException):
        _validate(_rule(rule_key="  "))
    with pytest.raises(HTTPException):
        _validate(_rule(heading=""))

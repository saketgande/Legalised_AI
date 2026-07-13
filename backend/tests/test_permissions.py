"""RBAC unit tests: permission grants and rung-gated approval."""
from app.permissions import (
    Permission,
    can,
    can_clear_rung,
    permissions_for,
    rank_of,
)


def test_admin_is_superuser():
    assert permissions_for("admin") == set(Permission)


def test_requester_is_minimal():
    perms = permissions_for("requester")
    assert Permission.REQUEST_CREATE in perms
    assert Permission.REQUEST_READ_OWN in perms
    assert Permission.REQUEST_READ_ALL not in perms
    assert Permission.REVIEW_DECIDE not in perms


def test_viewer_is_read_only():
    assert can("viewer", Permission.REQUEST_READ_ALL)
    assert not can("viewer", Permission.REVIEW_DECIDE)
    assert not can("viewer", Permission.REQUEST_CREATE)


def test_rank_ordering():
    assert rank_of("attorney") < rank_of("vp_legal") < rank_of("gc") < rank_of("admin")


def test_attorney_cannot_clear_senior_rungs():
    assert can_clear_rung("attorney", "none")               # rank 4 >= 0
    assert can_clear_rung("attorney", "requesting_manager") # rank 4 >= 3
    assert not can_clear_rung("attorney", "vp_legal")       # rank 4 < 5
    assert not can_clear_rung("attorney", "gc")             # rank 4 < 6


def test_gc_clears_everything():
    for rung in ("none", "requesting_manager", "vp_legal", "gc"):
        assert can_clear_rung("gc", rung)


def test_paralegal_cannot_decide_at_all():
    # no REVIEW_DECIDE grant -> cannot clear even a rung it would outrank
    assert not can_clear_rung("paralegal", "none")
    assert not can("paralegal", Permission.REVIEW_DECIDE)

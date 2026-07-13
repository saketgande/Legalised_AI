"""RBAC — the single source of truth for roles, permissions, and rung ranks.

Two layers of authorization:
  1. Permission grants (can this role take this kind of action at all?).
  2. Rung rank (is this person senior enough to approve *this* deviation?).

The second is what makes the approval ladder real: a deviation that triggers
the `gc` rung can only be approved by someone of GC rank or above — an attorney
approving it is a 403, not a silent pass.
"""
from __future__ import annotations

import enum


class Permission(str, enum.Enum):
    REQUEST_CREATE = "request:create"
    REQUEST_READ_ALL = "request:read_all"
    REQUEST_READ_OWN = "request:read_own"
    REVIEW_DECIDE = "review:decide"        # approve/reject changes + ladder steps
    REQUEST_SEND = "request:send"
    PLAYBOOK_READ = "playbook:read"
    ADMIN_MANAGE_USERS = "admin:manage_users"


# rank orders both roles and approval rungs on one scale
RANK: dict[str, int] = {
    "requester": 1,
    "viewer": 2,
    "paralegal": 3,
    "attorney": 4,
    "vp_legal": 5,
    "gc": 6,
    "admin": 7,
}

# an approval rung maps to the minimum rank that may clear it
RUNG_RANK: dict[str, int] = {
    "none": 0,
    "requesting_manager": 3,
    "vp_legal": 5,
    "gc": 6,
}

_ALL = set(Permission)
_STAFF = {
    Permission.REQUEST_CREATE, Permission.REQUEST_READ_ALL,
    Permission.REVIEW_DECIDE, Permission.REQUEST_SEND, Permission.PLAYBOOK_READ,
}

ROLE_PERMISSIONS: dict[str, set[Permission]] = {
    "admin": set(_ALL),
    "gc": set(_STAFF),
    "vp_legal": set(_STAFF),
    "attorney": set(_STAFF),
    "paralegal": {  # triages + files, but does not approve deviations
        Permission.REQUEST_CREATE, Permission.REQUEST_READ_ALL, Permission.PLAYBOOK_READ,
    },
    "legal_ops": {
        Permission.REQUEST_READ_ALL, Permission.PLAYBOOK_READ,
    },
    "requester": {Permission.REQUEST_CREATE, Permission.REQUEST_READ_OWN},
    "viewer": {Permission.REQUEST_READ_ALL, Permission.PLAYBOOK_READ},
}


def permissions_for(role: str) -> set[Permission]:
    return ROLE_PERMISSIONS.get(role, set())


def can(role: str, perm: Permission) -> bool:
    return perm in permissions_for(role)


def rank_of(role: str) -> int:
    return RANK.get(role, 0)


def can_clear_rung(role: str, rung: str) -> bool:
    """Rung-gated approval: senior enough AND holds the decide grant."""
    if not can(role, Permission.REVIEW_DECIDE):
        return False
    return rank_of(role) >= RUNG_RANK.get(rung, 0)

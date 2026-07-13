"""Dev-grade secret sealing for stored credentials (the polled inbox password).

This is deliberately NOT real cryptography: it XORs the plaintext with an
HMAC-SHA256 keystream derived from ``AUTH_SECRET``, so the DB never stores the
raw password and a database dump doesn't hand it over. It is reversible by anyone
with ``AUTH_SECRET`` — which is the point (the poller needs the password back).

Operational guidance: use a dedicated intake mailbox with an app password and a
restricted scope. Replace ``seal``/``unseal`` with KMS/Fernet before production;
the ``v1:`` version prefix lets a future implementation coexist. Interface stays
the same, so no caller moves.
"""
from __future__ import annotations

import base64
import hashlib
import hmac

from ..config import settings

_PREFIX = "v1:"


def _keystream(n: int) -> bytes:
    """HMAC-SHA256 counter-mode keystream of length n, keyed by AUTH_SECRET."""
    key = settings.auth_secret.encode("utf-8")
    out = bytearray()
    counter = 0
    while len(out) < n:
        block = hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:n])


def _xor(data: bytes) -> bytes:
    ks = _keystream(len(data))
    return bytes(a ^ b for a, b in zip(data, ks))


def seal(plaintext: str) -> str:
    raw = plaintext.encode("utf-8")
    return _PREFIX + base64.b64encode(_xor(raw)).decode("ascii")


def unseal(sealed: str) -> str:
    if not sealed.startswith(_PREFIX):
        # tolerate a legacy/plaintext value rather than crash the poller
        return sealed
    raw = base64.b64decode(sealed[len(_PREFIX):])
    return _xor(raw).decode("utf-8")

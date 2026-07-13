"""Tiny in-process sliding-window rate limiter for login brute-force protection.

Per-process (fine for a single-instance deploy); a multi-instance deploy would
swap this for Redis. Keyed by IP+email so one attacker can't lock out everyone.
"""
from __future__ import annotations

import time

_fails: dict[str, list[float]] = {}


def _recent(key: str, window: float) -> list[float]:
    now = time.time()
    xs = [t for t in _fails.get(key, []) if now - t < window]
    if xs:
        _fails[key] = xs
    else:
        _fails.pop(key, None)
    return xs


def too_many(key: str, *, max_fails: int = 8, window: float = 900) -> bool:
    return len(_recent(key, window)) >= max_fails


def record_failure(key: str, *, window: float = 900) -> None:
    _recent(key, window)
    _fails.setdefault(key, []).append(time.time())


def clear(key: str) -> None:
    _fails.pop(key, None)

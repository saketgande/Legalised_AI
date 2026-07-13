"""Tests for the hardening pass: production secret guard + login rate limiter."""
import pytest

from app import config
from app.services import ratelimit


# ————————————————————————— production guard —————————————————————————
def test_dev_guard_is_noop(monkeypatch):
    monkeypatch.setattr(config.settings, "environment", "development")
    monkeypatch.setattr(config.settings, "auth_secret", config.DEV_AUTH_SECRET)
    config.assert_production_secrets()  # must not raise in dev


def test_prod_blocks_dev_secret(monkeypatch):
    monkeypatch.setattr(config.settings, "environment", "production")
    monkeypatch.setattr(config.settings, "auth_secret", config.DEV_AUTH_SECRET)
    monkeypatch.setattr(config.settings, "intake_webhook_secret", "hook")
    with pytest.raises(RuntimeError):
        config.assert_production_secrets()


def test_prod_requires_webhook_secret(monkeypatch):
    monkeypatch.setattr(config.settings, "environment", "production")
    monkeypatch.setattr(config.settings, "auth_secret", "a-strong-random-secret-value")
    monkeypatch.setattr(config.settings, "intake_webhook_secret", "")
    with pytest.raises(RuntimeError):
        config.assert_production_secrets()


def test_prod_passes_with_hardened_config(monkeypatch):
    monkeypatch.setattr(config.settings, "environment", "production")
    monkeypatch.setattr(config.settings, "auth_secret", "a-strong-random-secret-value")
    monkeypatch.setattr(config.settings, "intake_webhook_secret", "hook-secret")
    config.assert_production_secrets()  # must not raise


# ————————————————————————— rate limiter —————————————————————————
def test_ratelimit_blocks_after_max():
    key = "test-key-1"
    ratelimit.clear(key)
    for _ in range(8):
        assert not ratelimit.too_many(key, max_fails=8)
        ratelimit.record_failure(key)
    assert ratelimit.too_many(key, max_fails=8)


def test_ratelimit_clear_resets():
    key = "test-key-2"
    for _ in range(8):
        ratelimit.record_failure(key)
    assert ratelimit.too_many(key, max_fails=8)
    ratelimit.clear(key)
    assert not ratelimit.too_many(key, max_fails=8)


def test_ratelimit_window_expiry():
    key = "test-key-3"
    ratelimit.clear(key)
    for _ in range(8):
        ratelimit.record_failure(key)
    # a zero-length window means nothing counts as recent
    assert not ratelimit.too_many(key, max_fails=8, window=0)

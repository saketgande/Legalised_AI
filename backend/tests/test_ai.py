"""Tests for the semantic AI layer's fallback (no network) + factory routing."""
from types import SimpleNamespace

from app.services.ai import ClaudeAIClient, HeuristicAIClient, get_ai_client


def _rule(clause_type):
    return SimpleNamespace(clause_type=clause_type, heading="H", preferred_position="p", preferred_body="b")


def test_heuristic_flags_missing_carveout():
    v = HeuristicAIClient().compare_clause(
        "liability shall not exceed the fees paid in the last months", _rule("limitation_of_liability"), {}
    )
    assert v is not None and v.matches is False and v.model == "heuristic"


def test_heuristic_accepts_carveout():
    v = HeuristicAIClient().compare_clause(
        "Except for breach of confidentiality, liability is capped.", _rule("limitation_of_liability"), {}
    )
    assert v is not None and v.matches is True


def test_heuristic_abstains_on_prose():
    # no model -> no opinion on prose clauses (returns None, so no fake SEM check)
    assert HeuristicAIClient().compare_clause("used solely for the purpose", _rule("purpose"), {}) is None


def test_factory_returns_heuristic_without_key(monkeypatch):
    from app import config
    monkeypatch.setattr(config.settings, "anthropic_api_key", None)
    assert isinstance(get_ai_client(), HeuristicAIClient)


def test_factory_returns_claude_with_key(monkeypatch):
    from app import config
    monkeypatch.setattr(config.settings, "anthropic_api_key", "sk-test")
    assert isinstance(get_ai_client(), ClaudeAIClient)


def test_claude_falls_back_on_network_error(monkeypatch):
    # when the HTTP call raises, ClaudeAIClient degrades to the heuristic (never breaks)
    from app.services import ai as ai_mod

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(ai_mod.httpx, "post", boom)
    client = ClaudeAIClient("sk-invalid", "claude-opus-4-8")
    v = client.compare_clause("liability capped, no carve out", _rule("limitation_of_liability"), {})
    assert v is not None and v.model == "heuristic"  # fell back


def test_claude_parses_a_valid_response(monkeypatch):
    from app.services import ai as ai_mod

    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {"content": [{"text": '{"matches": false, "note": "narrower than ours", "confidence": 0.7, "suggested_after": "Better clause."}'}]}

    monkeypatch.setattr(ai_mod.httpx, "post", lambda *a, **k: FakeResp())
    client = ClaudeAIClient("sk-test", "claude-opus-4-8")
    v = client.compare_clause("their clause", _rule("purpose"), {})
    assert v is not None and v.matches is False
    assert v.suggested_after == "Better clause." and v.model == "claude-opus-4-8"

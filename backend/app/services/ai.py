"""AI client for semantic clause comparison.

The engine's DETERMINISTIC checks (numbers, dates, presence) stay in code — the
things LLMs get wrong. The SEMANTIC layer — "does this prose actually meet our
position?" — routes here. Two implementations behind one factory:

  * ClaudeAIClient  — real Claude call (when ANTHROPIC_API_KEY is set).
  * HeuristicAIClient — keyword fallback so the demo runs with no key.

`compare_clause` returns None to mean "no semantic opinion" (skip), a verdict
otherwise. Claude failures fall back to the heuristic — the review never breaks
because the model is unavailable.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx

from ..config import settings


@dataclass
class SemanticVerdict:
    matches: bool                 # True = meets/exceeds our position (no deviation)
    note: str                     # <=20-word explanation (the SEM check detail)
    confidence: float
    model: str                    # "claude-opus-4-8" | "heuristic"
    suggested_after: str | None = None


class HeuristicAIClient:
    """No model behind this — deterministic keyword checks for the cases we can
    reason about without one; None (abstain) for prose we won't fake-analyze."""

    model = "heuristic"

    def compare_clause(self, clause_text: str, rule, ctx: dict) -> SemanticVerdict | None:
        if rule.clause_type == "limitation_of_liability":
            t = clause_text.lower()
            has_carveout = "confidential" in t and any(
                w in t for w in ("except", "nothing", "excluding", "other than")
            )
            return SemanticVerdict(
                matches=has_carveout,
                note="carve-out for confidentiality breach present" if has_carveout
                     else "no carve-out for breach of confidentiality — our position requires one",
                confidence=0.8,
                model=self.model,
            )
        return None  # abstain — no model to judge prose


_SYSTEM = (
    "You are senior in-house counsel reviewing a counterparty's NDA clause against "
    "your company's standard position. Judge strictly but fairly, from your company's "
    "perspective. Respond with ONLY a JSON object and no other text."
)


def _extract_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


class ClaudeAIClient:
    """Real semantic comparison via the Anthropic Messages API."""

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self._fallback = HeuristicAIClient()

    def compare_clause(self, clause_text: str, rule, ctx: dict) -> SemanticVerdict | None:
        user = (
            f"Our standard position for the '{rule.heading}' clause:\n{rule.preferred_position}\n\n"
            f"Our preferred clause language:\n{rule.preferred_body}\n\n"
            f"The counterparty's clause:\n{clause_text}\n\n"
            "Does the counterparty's clause meet or exceed our standard position "
            "(i.e., no worse for our company)? Return JSON: "
            '{"matches": boolean, "note": "<=20 word reason", "confidence": 0.0-1.0, '
            '"suggested_after": "<proposed replacement clause text if it does not match, else null>"}'
        )
        try:
            resp = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": 500,
                    "temperature": 0,
                    "system": _SYSTEM,
                    "messages": [{"role": "user", "content": user}],
                },
                timeout=30,
            )
            resp.raise_for_status()
            text = resp.json()["content"][0]["text"]
            data = _extract_json(text)
            if data is None or "matches" not in data:
                return self._fallback.compare_clause(clause_text, rule, ctx)
            conf = float(data.get("confidence", 0.7))
            return SemanticVerdict(
                matches=bool(data["matches"]),
                note=str(data.get("note", "")).strip()[:200],
                confidence=max(0.0, min(1.0, conf)),
                model=self.model,
                suggested_after=(data.get("suggested_after") or None),
            )
        except Exception:
            # network / API / parse failure -> never break the review
            return self._fallback.compare_clause(clause_text, rule, ctx)


def get_ai_client():
    if settings.anthropic_api_key:
        return ClaudeAIClient(settings.anthropic_api_key, settings.anthropic_model)
    return HeuristicAIClient()

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


@dataclass
class IntakeParse:
    intent: str                   # "outbound" | "inbound" | "other"
    counterparty: str | None
    nda_type: str                 # MUTUAL | ONE_WAY
    purpose: str
    term_months: int
    jurisdiction: str
    reply: str                    # natural-language reply for the chatbot
    confidence: float
    model: str


_PURPOSE_KEYWORDS = {
    "vendor": "vendor_evaluation", "supplier": "vendor_evaluation",
    "sales": "sales_evaluation", "customer": "sales_evaluation", "eval": "sales_evaluation",
    "hir": "hiring", "recruit": "hiring", "candidate": "hiring",
    "partner": "partnership_exploration", "collab": "partnership_exploration",
    "litig": "litigation_support", "dispute": "litigation_support",
}
_JURIS_CODES = {
    "delaware": "US-DE", "california": "US-CA", "new york": "US-NY",
    "england": "UK", "wales": "UK", "united kingdom": "UK", "germany": "EU-DE",
}


def _guess_intake(text: str) -> IntakeParse:
    import re

    t = text.lower()
    intent = "outbound"
    if any(w in t for w in ("review their", "they sent", "counterparty sent", "their paper", "sent us", "sent over", "attached")):
        intent = "inbound"

    counterparty = None
    m = re.search(r"\bwith\s+([A-Z][\w.&'-]*(?:\s+[A-Z][\w.&'-]*){0,3})", text)
    if m:
        counterparty = re.sub(r"\s+(for|to|regarding|about)$", "", m.group(1)).strip()

    nda_type = "ONE_WAY" if any(w in t for w in ("one-way", "one way", "unilateral")) else "MUTUAL"
    purpose = next((v for k, v in _PURPOSE_KEYWORDS.items() if k in t), "sales_evaluation")

    term = 24
    tm = re.search(r"(\d+)\s*(month|year)", t)
    if tm:
        term = int(tm.group(1)) * (12 if tm.group(2) == "year" else 1)

    jurisdiction = next((code for name, code in _JURIS_CODES.items() if name in t), "US")

    if counterparty:
        reply = (f"Got it — a {'one-way' if nda_type == 'ONE_WAY' else 'mutual'} NDA with "
                 f"{counterparty} for {purpose.replace('_', ' ')} ({term} months). Filing it now.")
    else:
        reply = "Happy to help with an NDA. Who's the counterparty (the other company)?"

    return IntakeParse(intent, counterparty, nda_type, purpose, term, jurisdiction, reply, 0.55, "heuristic")


class HeuristicAIClient:
    """No model behind this — deterministic keyword checks for the cases we can
    reason about without one; None (abstain) for prose we won't fake-analyze."""

    model = "heuristic"

    def parse_intake(self, text: str) -> IntakeParse:
        return _guess_intake(text)

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

    def _call(self, system: str, user: str) -> dict | None:
        try:
            resp = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": self.model, "max_tokens": 500, "temperature": 0,
                      "system": system, "messages": [{"role": "user", "content": user}]},
                timeout=30,
            )
            resp.raise_for_status()
            return _extract_json(resp.json()["content"][0]["text"])
        except Exception:
            return None

    def parse_intake(self, text: str) -> IntakeParse:
        system = (
            "You triage inbound requests to a corporate legal team. Extract the NDA request "
            "from the message. Respond with ONLY a JSON object."
        )
        user = (
            f"Message:\n{text}\n\n"
            "Return JSON: {\"intent\": \"outbound\"|\"inbound\"|\"other\", "
            "\"counterparty\": \"<company name or null>\", \"nda_type\": \"MUTUAL\"|\"ONE_WAY\", "
            "\"purpose\": \"sales_evaluation\"|\"vendor_evaluation\"|\"hiring\"|\"partnership_exploration\"|\"litigation_support\", "
            "\"term_months\": <int>, \"jurisdiction\": \"US\"|\"US-CA\"|\"US-NY\"|\"US-DE\"|\"UK\"|\"EU-DE\", "
            "\"reply\": \"<one friendly sentence back to the requester>\", \"confidence\": 0.0-1.0}. "
            "intent is 'inbound' if they want us to review a contract the other side sent, else 'outbound'."
        )
        data = self._call(system, user)
        if not data or "intent" not in data:
            return self._fallback.parse_intake(text)
        try:
            return IntakeParse(
                intent=str(data.get("intent", "outbound")),
                counterparty=(data.get("counterparty") or None),
                nda_type="ONE_WAY" if str(data.get("nda_type")) == "ONE_WAY" else "MUTUAL",
                purpose=str(data.get("purpose", "sales_evaluation")),
                term_months=int(data.get("term_months", 24) or 24),
                jurisdiction=str(data.get("jurisdiction", "US")),
                reply=str(data.get("reply", "")).strip()[:300],
                confidence=max(0.0, min(1.0, float(data.get("confidence", 0.7)))),
                model=self.model,
            )
        except (TypeError, ValueError):
            return self._fallback.parse_intake(text)

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

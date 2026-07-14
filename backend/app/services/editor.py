"""Drafting Editor — Harvey/Legora's "Editor" surface.

Draft or revise contract language in place. The AI streams a replacement for the
selected text (or new text at the cursor), grounded in the firm's playbook
positions, and the user accepts or rejects it — nothing is auto-applied.

Same discipline as the rest of the platform:
  * grounding retrieval is DETERMINISTIC and org-scoped (playbook rules), done up
    front while the request session is alive;
  * generation is the AI layer — Claude streams a clean clause when keyed; with
    no key we ASSEMBLE from the best-matching playbook clause (Frontdoor's core
    competency: assemble, don't free-generate), so the editor always responds.

Advisory only. Each generation is sealed on the audit chain (`editor.generate`).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from typing import Iterator

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Playbook, PlaybookRule, User
from .assistant import _score, _tokens

_MAX_GROUNDING = 4


@dataclass
class Grounding:
    rule_key: str
    heading: str
    preferred: str
    url: str = "/admin/playbook"


def retrieve_grounding(db: Session, user: User, instruction: str, selection: str = "") -> list[Grounding]:
    """Top playbook rules relevant to the drafting instruction (org-scoped)."""
    qtok = set(_tokens(f"{instruction} {selection}"))
    pbs = list(db.execute(select(Playbook).where(Playbook.org_id == user.org_id)).scalars())
    if not pbs:
        return []
    rules = list(db.execute(
        select(PlaybookRule).where(PlaybookRule.playbook_id.in_([p.id for p in pbs]))
    ).scalars())
    scored: list[tuple[int, PlaybookRule]] = []
    for r in rules:
        s = _score(qtok, f"{r.heading} {r.clause_type} {r.preferred_position} {r.rationale}")
        if s > 0:
            scored.append((s, r))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [Grounding(r.rule_key, r.heading, (r.preferred_body or r.preferred_position or "").strip())
            for _, r in scored[:_MAX_GROUNDING]]


_SYSTEM = (
    "You are a senior legal drafter for an in-house team. Draft or revise the "
    "requested contract language so it aligns with the FIRM POSITIONS provided. "
    "Return ONLY the resulting clause text — no preamble, no explanation, no "
    "markdown fences, no surrounding quotes. Keep it clean, precise, and ready to "
    "paste straight into the contract."
)


def _grounding_block(grounding: list[Grounding]) -> str:
    if not grounding:
        return "(no specific firm position on file — draft to a reasonable market-standard.)"
    return "\n".join(f"- {g.heading} ({g.rule_key}): {g.preferred}" for g in grounding)


def draft_stream(instruction: str, selection: str, grounding: list[Grounding]) -> Iterator[str]:
    if settings.anthropic_api_key:
        try:
            yield from _claude_stream(instruction, selection, grounding)
            return
        except Exception:
            pass
    yield from _assemble_stream(instruction, selection, grounding)


def _claude_stream(instruction: str, selection: str, grounding: list[Grounding]) -> Iterator[str]:
    if selection.strip():
        user = (f"CURRENT TEXT:\n{selection}\n\nFIRM POSITIONS:\n{_grounding_block(grounding)}"
                f"\n\nINSTRUCTION: {instruction}")
    else:
        user = (f"FIRM POSITIONS:\n{_grounding_block(grounding)}\n\n"
                f"INSTRUCTION (draft new text): {instruction}")
    with httpx.stream(
        "POST", "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": settings.anthropic_model, "max_tokens": 1200, "temperature": 0.2,
              "system": _SYSTEM, "stream": True,
              "messages": [{"role": "user", "content": user}]},
        timeout=60,
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                evt = json.loads(payload)
            except Exception:
                continue
            if evt.get("type") == "content_block_delta":
                delta = evt.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    yield delta["text"]


def _assemble_stream(instruction: str, selection: str, grounding: list[Grounding]) -> Iterator[str]:
    """No model — assemble from the best-matching playbook clause, streamed word-wise."""
    if grounding and grounding[0].preferred:
        text = grounding[0].preferred
        words = text.split(" ")
        for i in range(0, len(words), 6):
            yield " ".join(words[i:i + 6]) + (" " if i + 6 < len(words) else "")
        return
    yield ("[No matching playbook clause for this instruction, and no model is "
           "configured. Set ANTHROPIC_API_KEY to draft with AI, or add a playbook "
           "rule for this clause type.]")


def grounding_payload(grounding: list[Grounding]) -> list[dict]:
    return [asdict(g) for g in grounding]

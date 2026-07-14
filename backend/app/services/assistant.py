"""Grounded legal assistant — the Harvey-style daily driver.

The assistant answers questions **only from Frontdoor's own data**, scoped to
what the caller is allowed to read, and cites a source for every claim. It is
advisory: it never mutates state. Any *action* it suggests (draft an answer,
run a redline, send) still flows through the existing governed endpoints — the
audit chain and human-approval gates are untouched.

Two layers, mirroring the rest of the platform:

  * ``retrieve_context`` — DETERMINISTIC retrieval over clauses, playbook rules,
    and requests. Keyword-scored, permission-scoped, org-scoped. This is the
    grounding; it runs with or without a model.
  * ``answer_stream`` — the SYNTHESIS. Streams a grounded answer from Claude
    when ``ANTHROPIC_API_KEY`` is set, citing sources by ``[n]``. With no key it
    streams a deterministic extract of the top sources — the demo never breaks.

Every retrieved chunk carries a stable ``[n]`` index and a ``url`` the UI turns
into a clickable citation.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from typing import Iterator

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    Clause,
    Counterparty,
    Document,
    DocumentVersion,
    Playbook,
    PlaybookRule,
    Request,
    User,
)
from ..permissions import Permission, can

_STOP = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "for",
    "is", "are", "was", "were", "be", "our", "we", "us", "you", "your", "it",
    "this", "that", "these", "those", "with", "as", "at", "by", "from", "do",
    "does", "did", "can", "could", "should", "would", "what", "which", "how",
    "when", "who", "whom", "why", "about", "into", "than", "then", "there",
    "have", "has", "had", "will", "shall", "may", "not", "no", "any", "all",
}

_MAX_CANDIDATE_REQUESTS = 200   # cap the working set so retrieval stays fast
_MAX_CHUNKS = 8                 # sources handed to the model / shown to the user


@dataclass
class Chunk:
    """One grounded, citable source."""
    n: int              # 1-indexed citation number (filled at ranking time)
    kind: str           # "clause" | "playbook" | "request"
    title: str          # human label, e.g. "REQ-2026-1055 · §4 Confidentiality"
    snippet: str        # the text the model may quote / the user reads
    request_id: str | None = None   # deep-link target when the source is a request/clause
    url: str | None = None          # frontend route the citation opens


def _tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2 and w not in _STOP]


def _score(query_tokens: set[str], text: str) -> int:
    if not query_tokens:
        return 0
    hay = (text or "").lower()
    return sum(hay.count(t) for t in query_tokens)


def _readable_requests(db: Session, user: User, scope_request_id: str | None) -> list[Request]:
    """The request working set the caller may read (org-scoped, permission-scoped)."""
    q = select(Request).where(Request.org_id == user.org_id)
    if scope_request_id:
        q = q.where(Request.id == scope_request_id)
    rows = list(db.execute(q.order_by(Request.created_at.desc()).limit(_MAX_CANDIDATE_REQUESTS)).scalars())
    if can(user.role, Permission.REQUEST_READ_ALL):
        return rows
    if can(user.role, Permission.REQUEST_READ_OWN):
        # requester-scoped: only requests this user filed (matched via requester person → user email)
        own = {r.id for r in rows if _owns(db, user, r)}
        return [r for r in rows if r.id in own]
    return []


def _owns(db: Session, user: User, r: Request) -> bool:
    from ..models import Person
    p = db.get(Person, r.requester_id)
    return bool(p and p.email and user.email and p.email.lower() == user.email.lower())


def retrieve_context(db: Session, user: User, query: str, scope_request_id: str | None = None) -> list[Chunk]:
    """Deterministic, permission-scoped retrieval. Returns up to _MAX_CHUNKS ranked sources."""
    qtok = set(_tokens(query))
    reqs = _readable_requests(db, user, scope_request_id)
    req_by_id = {r.id: r for r in reqs}
    cp_names = {r.counterparty_id: db.get(Counterparty, r.counterparty_id) for r in reqs}

    scored: list[tuple[int, Chunk]] = []

    # ── clauses of the readable requests' current documents ──
    doc_ids = [r.document_id for r in reqs if r.document_id]
    if doc_ids:
        docs = list(db.execute(select(Document).where(Document.id.in_(doc_ids))).scalars())
        for doc in docs:
            if not doc.current_version_id:
                continue
            clauses = list(db.execute(
                select(Clause).where(Clause.document_version_id == doc.current_version_id).order_by(Clause.ordinal)
            ).scalars())
            r = req_by_id.get(doc.request_id)
            ref = r.ref if r else doc.title
            for c in clauses:
                body = f"{c.heading} {c.body_text}"
                s = _score(qtok, body)
                # when scoped to a single request, include its clauses even on a 0 score
                if s == 0 and not scope_request_id:
                    continue
                title = f"{ref} · §{c.section_no or c.ordinal} {c.heading}".strip()
                scored.append((s, Chunk(0, "clause", title, c.body_text[:600],
                                        request_id=doc.request_id, url=f"/t/{doc.request_id}")))

    # ── playbook rules (org-scoped) ──
    pbs = list(db.execute(select(Playbook).where(Playbook.org_id == user.org_id)).scalars())
    if pbs:
        rules = list(db.execute(
            select(PlaybookRule).where(PlaybookRule.playbook_id.in_([p.id for p in pbs]))
        ).scalars())
        for rule in rules:
            body = f"{rule.heading} {rule.preferred_position} {rule.rationale} {rule.walk_away_text}"
            s = _score(qtok, body)
            if s == 0:
                continue
            pos = rule.preferred_position or rule.rationale or rule.preferred_body
            wa = f"  Walk-away: {rule.walk_away_text}" if rule.walk_away_text else ""
            scored.append((s + 1, Chunk(0, "playbook", f"Playbook · {rule.rule_key} {rule.heading}",
                                        f"{pos}{wa}"[:600], url="/admin/playbook")))

    # ── request summaries (ref / counterparty / purpose / state) ──
    for r in reqs:
        cp = cp_names.get(r.counterparty_id)
        cp_name = cp.name if cp else ""
        body = f"{r.ref} {cp_name} {r.purpose} {r.type} {r.state.value} {r.jurisdiction}"
        s = _score(qtok, body)
        if s == 0 and not (scope_request_id and r.id == scope_request_id):
            continue
        summary = (f"{r.type} · {r.direction.value.lower()} · state {r.state.value.replace('_', ' ').lower()}"
                   f" · {cp_name or 'counterparty'} · purpose: {r.purpose}"
                   f" · jurisdiction {r.jurisdiction} · {r.term_months}mo"
                   + (f" · round {r.round}" if r.round > 1 else ""))
        scored.append((s + (5 if scope_request_id else 0),
                       Chunk(0, "request", f"{r.ref} · {cp_name}".strip(" ·"), summary,
                             request_id=r.id, url=f"/t/{r.id}")))

    scored.sort(key=lambda t: t[0], reverse=True)
    top = [c for _, c in scored[:_MAX_CHUNKS]]
    for i, c in enumerate(top, start=1):
        c.n = i
    return top


# ───────────────────────── synthesis (streaming) ─────────────────────────

_SYSTEM = (
    "You are Frontdoor's legal assistant for an in-house legal team. Answer the "
    "user's question using ONLY the numbered SOURCES provided. Cite the sources "
    "you rely on inline as [1], [2], etc. — every factual claim needs a citation. "
    "If the sources don't contain the answer, say so plainly and suggest what to "
    "look at next. Be concise, practical, and lawyerly. Never invent contract "
    "terms, parties, dates, or numbers that aren't in the sources."
)


def _context_block(chunks: list[Chunk]) -> str:
    return "\n\n".join(f"[{c.n}] ({c.kind}) {c.title}\n{c.snippet}" for c in chunks)


def answer_stream(query: str, chunks: list[Chunk]) -> Iterator[str]:
    """Yield the grounded answer in text deltas. Claude when keyed, extract otherwise."""
    if not chunks:
        yield ("I couldn't find anything in your workspace that matches that. Try naming a "
               "counterparty, a request reference (like REQ-2026-1055), or a clause type "
               "(confidentiality, liability, term).")
        return
    if settings.anthropic_api_key:
        try:
            yield from _claude_stream(query, chunks)
            return
        except Exception:
            pass  # fall through to the deterministic extract — the assistant never dead-ends
    yield from _extract_stream(query, chunks)


def _claude_stream(query: str, chunks: list[Chunk]) -> Iterator[str]:
    user = f"SOURCES:\n{_context_block(chunks)}\n\nQUESTION: {query}"
    with httpx.stream(
        "POST", "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": settings.anthropic_model, "max_tokens": 900, "temperature": 0,
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


def _extract_stream(query: str, chunks: list[Chunk]) -> Iterator[str]:
    """Deterministic grounded extract — no model. Honest about what it is."""
    yield f"Here's what I found in your workspace for that ({len(chunks)} source"
    yield "s" if len(chunks) != 1 else ""
    yield "):\n\n"
    for c in chunks[:4]:
        snippet = re.sub(r"\s+", " ", c.snippet).strip()
        if len(snippet) > 240:
            snippet = snippet[:240].rstrip() + "…"
        yield f"- **{c.title}** [{c.n}] — {snippet}\n"
    yield ("\n_Grounded extract from your sources (no model configured). Set "
           "`ANTHROPIC_API_KEY` for a synthesized answer._")


def sources_payload(chunks: list[Chunk]) -> list[dict]:
    return [asdict(c) for c in chunks]

"""Tabular Review — Legora's signature surface.

Pick a set of documents, write a question per column, and every cell is an
extracted answer for (document × question), linked to its source section. The
grid fills progressively as each cell resolves.

Same two-layer discipline as the rest of the platform:
  * retrieval + row assembly is DETERMINISTIC and permission-scoped (DB work,
    done up front while the request session is alive);
  * cell extraction is the AI layer — Claude for a crisp answer when keyed, a
    deterministic best-clause extract otherwise, so the grid always fills.

Everything is advisory and read-only. One `tabular.review` row seals the whole
run on the audit chain — not one row per cell (that would flood the ledger).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Clause, Counterparty, Document, Request, User
from .assistant import _readable_requests, _score, _tokens

MAX_ROWS = 60
MAX_COLS = 12


@dataclass
class DocRow:
    request_id: str
    ref: str
    counterparty: str
    type: str
    doc_title: str
    url: str


@dataclass
class _ClauseLite:
    section: str
    heading: str
    body: str


def _clauses_for(db: Session, req: Request) -> list[_ClauseLite]:
    if not req.document_id:
        return []
    doc = db.get(Document, req.document_id)
    if not doc or not doc.current_version_id:
        return []
    rows = list(db.execute(
        select(Clause).where(Clause.document_version_id == doc.current_version_id).order_by(Clause.ordinal)
    ).scalars())
    return [_ClauseLite(str(c.section_no or c.ordinal), c.heading or "", c.body_text or "") for c in rows]


def list_documents(db: Session, user: User) -> list[DocRow]:
    """The reviewable corpus: readable requests that carry a generated/uploaded document."""
    reqs = [r for r in _readable_requests(db, user, None) if r.document_id]
    out: list[DocRow] = []
    for r in reqs:
        cp = db.get(Counterparty, r.counterparty_id)
        out.append(DocRow(
            request_id=r.id, ref=r.ref, counterparty=(cp.name if cp else ""),
            type=r.type, doc_title=f"{r.type} · {r.direction.value.lower()}",
            url=f"/t/{r.id}",
        ))
    return out


def prepare_rows(db: Session, user: User, request_ids: list[str]) -> tuple[list[DocRow], dict[str, list[_ClauseLite]]]:
    """Authorize + fetch clauses for the selected rows, up front (session alive)."""
    readable = {r.id: r for r in _readable_requests(db, user, None)}
    rows: list[DocRow] = []
    clauses: dict[str, list[_ClauseLite]] = {}
    for rid in request_ids[:MAX_ROWS]:
        r = readable.get(rid)
        if not r or not r.document_id:
            continue  # silently skip ids the caller can't read / that carry no doc
        cp = db.get(Counterparty, r.counterparty_id)
        rows.append(DocRow(r.id, r.ref, cp.name if cp else "", r.type,
                           f"{r.type} · {r.direction.value.lower()}", f"/t/{r.id}"))
        clauses[r.id] = _clauses_for(db, r)
    return rows, clauses


# ───────────────────────── cell extraction ─────────────────────────

@dataclass
class Cell:
    request_id: str
    col: int
    value: str
    section: str          # the source section, e.g. "10" (empty when not found)
    url: str | None       # deep-link to the document


_CELL_SYSTEM = (
    "You extract one fact from a contract. Given the clauses of ONE contract and a "
    "QUESTION, answer in at most 12 words — a value, not a sentence (e.g. '12 months' "
    "fees', 'Delaware', 'Mutual', 'Not addressed'). Also return the section number you "
    "read it from. If the contract doesn't address it, value must be 'Not addressed' and "
    'section "". Return ONLY JSON: {"value": "...", "section": "..."}.'
)


def _cell_context(clauses: list[_ClauseLite]) -> str:
    return "\n".join(f"§{c.section} {c.heading}: {c.body}" for c in clauses)[:6000]


def _extract_claude(question: str, clauses: list[_ClauseLite]) -> tuple[str, str] | None:
    try:
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": settings.anthropic_model, "max_tokens": 120, "temperature": 0,
                  "system": _CELL_SYSTEM,
                  "messages": [{"role": "user",
                                "content": f"CONTRACT CLAUSES:\n{_cell_context(clauses)}\n\nQUESTION: {question}"}]},
            timeout=30,
        )
        resp.raise_for_status()
        text = resp.json()["content"][0]["text"]
        m = re.search(r"\{.*\}", text, re.DOTALL)
        data = json.loads(m.group(0) if m else text)
        return str(data.get("value", "")).strip(), str(data.get("section", "")).strip()
    except Exception:
        return None


def _extract_heuristic(question: str, clauses: list[_ClauseLite]) -> tuple[str, str]:
    """No model — surface the most relevant clause as the cell value, honestly."""
    qtok = set(_tokens(question))
    best, best_score = None, 0
    for c in clauses:
        s = _score(qtok, f"{c.heading} {c.body}")
        if s > best_score:
            best, best_score = c, s
    if not best or best_score == 0:
        return "Not addressed", ""
    snippet = re.sub(r"\s+", " ", best.body).strip()
    if len(snippet) > 160:
        snippet = snippet[:160].rstrip() + "…"
    return snippet, best.section


def extract_cell(question: str, clauses: list[_ClauseLite], request_id: str, col: int, url: str | None) -> Cell:
    if not clauses:
        return Cell(request_id, col, "No document", "", url)
    if settings.anthropic_api_key:
        got = _extract_claude(question, clauses)
        if got is not None:
            return Cell(request_id, col, got[0] or "Not addressed", got[1], url)
    value, section = _extract_heuristic(question, clauses)
    return Cell(request_id, col, value, section, url)


def rows_payload(rows: list[DocRow]) -> list[dict]:
    return [asdict(r) for r in rows]


def cell_payload(c: Cell) -> dict:
    return asdict(c)

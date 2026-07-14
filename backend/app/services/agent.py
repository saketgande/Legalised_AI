"""Agentic workflow runner — Harvey's Workflow-Agent surface.

State a goal in plain language; the agent PLANS a multi-step run, EXECUTES each
step against Frontdoor's real engines (classification, contract summary, the risk
engine, the redline engine, the playbook), streams progress, and SYNTHESIZES a
governed recommendation.

It is an orchestrator over surfaces that already exist — it reads and recommends,
it never mutates state. Any action it proposes still flows through the governed
endpoints (human approval + audit). One `agent.run` row seals the run on the chain.

DB work (gathering the request's clauses / risk / redlines / playbook grounding)
happens up front while the session is alive; the streaming generator only shapes
that in-memory context into steps + a synthesized recommendation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterator

import httpx

from ..config import settings
from .tabular import _ClauseLite, _extract_heuristic

_KEY_QUESTIONS = [
    ("Liability cap", "limitation of liability cap"),
    ("Governing law", "governing law jurisdiction"),
    ("Term", "term length duration"),
]


@dataclass
class Step:
    key: str
    title: str


def plan(goal: str, scoped: bool) -> list[Step]:
    """Deterministic planner — decompose the goal into steps over the real engines."""
    if scoped:
        return [
            Step("understand", "Understand the goal"),
            Step("summarize", "Summarize the contract"),
            Step("risk", "Assess risk"),
            Step("redlines", "Review open redlines"),
            Step("recommend", "Recommend next steps"),
        ]
    return [
        Step("understand", "Understand the goal"),
        Step("search", "Search the workspace"),
        Step("recommend", "Recommend next steps"),
    ]


def _intent(goal: str) -> str:
    g = goal.lower()
    if any(w in g for w in ("draft", "counter", "rewrite", "clause")):
        return "draft / counter-proposal"
    if any(w in g for w in ("risk", "exposure", "dangerous")):
        return "risk assessment"
    if any(w in g for w in ("review", "redline", "check", "compare")):
        return "review against playbook"
    if any(w in g for w in ("expire", "renew", "renewal")):
        return "renewal / lifecycle"
    return "analysis & recommendation"


def _clause_lites(clauses: list[dict]) -> list[_ClauseLite]:
    return [_ClauseLite(str(c.get("section_no") or c.get("ordinal") or ""),
                        c.get("heading") or "", c.get("body_text") or "") for c in clauses]


# ───────────────────────── step execution ─────────────────────────

def run_steps(goal: str, ctx: dict, steps: list[Step]) -> Iterator[str]:
    """Yield SSE data lines: plan → step results → streamed recommendation → done."""
    yield _frame({"type": "plan", "steps": [{"key": s.key, "title": s.title} for s in steps]})

    facts: list[str] = []  # accumulate for the final synthesis

    for s in steps:
        if s.key == "recommend":
            continue  # handled last, streamed
        result, sources = _run_one(s.key, goal, ctx)
        facts.append(f"{s.title}: {result}")
        yield _frame({"type": "step", "key": s.key, "status": "done", "result": result, "sources": sources})

    # ── final synthesis (streamed) ──
    yield _frame({"type": "step", "key": "recommend", "status": "running"})
    acc = ""
    for delta in _recommend_stream(goal, ctx, facts):
        acc += delta
        yield _frame({"type": "delta", "key": "recommend", "text": delta})
    rec_sources = []
    if ctx.get("scope_request_id"):
        rec_sources = [{"title": ctx["scope_ref"], "url": f"/t/{ctx['scope_request_id']}"}]
    yield _frame({"type": "step", "key": "recommend", "status": "done", "result": acc, "sources": rec_sources})
    yield _frame({"type": "done"})


def _run_one(key: str, goal: str, ctx: dict) -> tuple[str, list[dict]]:
    if key == "understand":
        scope = f" · scoped to {ctx['scope_ref']}" if ctx.get("scope_ref") else " · across your workspace"
        return f"Interpreted as a {_intent(goal)} task{scope}.", []

    if key == "summarize":
        cl = _clause_lites(ctx.get("clauses", []))
        if not cl:
            return "No document attached to this request yet.", []
        lines = []
        for label, q in _KEY_QUESTIONS:
            val, section = _extract_heuristic(q, cl)
            sec = f" (§{section})" if section else ""
            lines.append(f"{label}: {val}{sec}")
        src = [{"title": f"{ctx['scope_ref']} · document", "url": f"/t/{ctx['scope_request_id']}"}]
        return " · ".join(lines), src

    if key == "risk":
        risk = ctx.get("risk")
        if not risk:
            return "No risk assessment on record for this request.", []
        top = ", ".join(f.get("label", "") for f in (risk.get("factors") or [])[:3]) or "no factors raised"
        return f"{risk['band']} · {risk['score']}/100 — {top}.", [{"title": f"{ctx['scope_ref']} · risk", "url": f"/t/{ctx['scope_request_id']}"}]

    if key == "redlines":
        review = ctx.get("review")
        if not review:
            return "No redline review has been run on this request.", []
        pending = review.get("pending", 0)
        top = review.get("top", "")
        if pending == 0:
            return "No pending redlines — every proposed change is decided.", []
        return f"{pending} pending redline{'s' if pending != 1 else ''}. Highest: {top}.", [{"title": f"{ctx['scope_ref']} · redlines", "url": f"/t/{ctx['scope_request_id']}"}]

    if key == "search":
        hits = ctx.get("search_hits", [])
        if not hits:
            return "Nothing in your workspace matched that goal.", []
        titles = "; ".join(h["title"] for h in hits[:3])
        return f"Found {len(hits)} relevant item{'s' if len(hits) != 1 else ''}: {titles}.", hits[:5]

    return "—", []


# ───────────────────────── recommendation synthesis ─────────────────────────

_REC_SYSTEM = (
    "You are a senior in-house counsel's chief of staff. Given a GOAL and the "
    "FINDINGS your team gathered, write a short, decisive recommendation: 2–4 "
    "numbered next steps, each concrete and owner-oriented (who does what). Ground "
    "every step in the findings — never invent facts. Be brief and practical."
)


def _recommend_stream(goal: str, ctx: dict, facts: list[str]) -> Iterator[str]:
    if settings.anthropic_api_key:
        try:
            yield from _claude_rec(goal, facts)
            return
        except Exception:
            pass
    yield from _rec_heuristic(goal, ctx)


def _claude_rec(goal: str, facts: list[str]) -> Iterator[str]:
    user = "GOAL: " + goal + "\n\nFINDINGS:\n" + "\n".join(f"- {f}" for f in facts)
    with httpx.stream(
        "POST", "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": settings.anthropic_model, "max_tokens": 600, "temperature": 0.2,
              "system": _REC_SYSTEM, "stream": True,
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
                d = evt.get("delta") or {}
                if d.get("type") == "text_delta" and d.get("text"):
                    yield d["text"]


def _rec_heuristic(goal: str, ctx: dict) -> Iterator[str]:
    """No model — a decisive recommendation assembled from the gathered facts."""
    steps: list[str] = []
    risk = ctx.get("risk")
    review = ctx.get("review")
    if review and review.get("pending", 0) > 0:
        rung = review.get("top_rung") or "the required approver"
        steps.append(f"Clear the {review['pending']} pending redline(s) — the highest needs {rung}.")
    if risk and risk.get("band") in ("HIGH", "CRITICAL"):
        steps.append(f"Escalate: risk is {risk['band']} ({risk['score']}/100) — get sign-off before sending.")
    if ctx.get("scope_request_id"):
        steps.append("Once the ladder is cleared and every redline decided, send the counter-proposal for signature.")
    else:
        steps.append("Open the most relevant matter above and run a scoped review for specifics.")
    if not steps:
        steps.append("No blockers found — this can proceed on the standard path.")
    header = "Recommended next steps:\n"
    yield header
    for i, s in enumerate(steps, 1):
        yield f"{i}. {s}\n"
    yield "\n_Assembled from the findings above (no model configured). Set ANTHROPIC_API_KEY for a synthesized plan._"


def _frame(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"

"""The Supervisor feed — one decision stream across the whole platform.

Frontdoor's spine is human-approval-on-everything. This service surfaces that
spine as a single feed: every point where the AI (or the pipeline) has done work
that now awaits a human call, aggregated across modules into one prioritized list.

It is a READ aggregation over existing state — it invents no new schema and takes
no action. Each item names *what the AI did*, *why*, and *the governed action* the
UI should offer (which still routes through the existing approve/send/renew
endpoints, each chain-sealed). The feed is the daily driver; the features that
produce these items are the workforce behind it.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import RequestState, User
from .assistant import _readable_requests
from .contracts import contract_registry
from .redline import latest_run

# severity → sort weight (critical first)
_SEV_RANK = {"critical": 0, "warn": 1, "normal": 2}
_RUNG_RANK = {"none": 0, "requesting_manager": 3, "vp_legal": 5, "gc": 6}


@dataclass
class Action:
    key: str          # "approve" | "edit" | "reject" | "send" | "renew" | "open" | "review"
    label: str
    primary: bool = False


@dataclass
class Decision:
    id: str           # stable: "{kind}:{request_id}"
    kind: str         # "advice_answer" | "redlines" | "ready_to_send" | "renewal"
    request_id: str
    ref: str
    title: str        # counterparty / advice subject
    actor: str        # who did the work ("🤖 Agent" / "Pipeline")
    headline: str     # what was done
    detail: str       # why / context
    severity: str     # "critical" | "warn" | "normal"
    actions: list[Action] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


def _preview(text: str | None, n: int = 220) -> str:
    t = " ".join((text or "").split())
    return (t[:n].rstrip() + "…") if len(t) > n else t


def list_decisions(db: Session, user: User) -> list[Decision]:
    reqs = _readable_requests(db, user, None)
    out: list[Decision] = []

    from ..routers.requests import _type_info

    for r in reqs:
        cp = _cp_name(db, r)
        advice = _type_info(db, r)[1] == "ADVICE"

        # 1) an AI-drafted advice answer awaiting approval
        if advice and r.state == RequestState.IN_REVIEW and r.resolution_draft:
            out.append(Decision(
                id=f"advice_answer:{r.id}", kind="advice_answer", request_id=r.id, ref=r.ref,
                title=r.purpose or r.type or "Legal question", actor="🤖 Agent",
                headline="Drafted an answer — awaiting your approval",
                detail=_preview(r.resolution_draft), severity="normal",
                actions=[Action("approve", "Approve answer", True), Action("edit", "Edit"), Action("open", "Open")],
                meta={"draft": r.resolution_draft},
            ))
            continue

        if not advice:
            run = latest_run(db, r.id)
            pending = [c for c in (run.changes if run else []) if c.decision == "PENDING"]
            # 2) proposed redlines awaiting a decision
            if pending:
                top = max(pending, key=lambda c: _RUNG_RANK.get(c.triggered_rung or "none", 0))
                band = _risk_band(db, r)
                sev = "critical" if band in ("HIGH", "CRITICAL") else "warn"
                out.append(Decision(
                    id=f"redlines:{r.id}", kind="redlines", request_id=r.id, ref=r.ref,
                    title=cp, actor="🤖 Agent",
                    headline=f"Proposed {len(pending)} redline{'s' if len(pending) != 1 else ''} vs the playbook",
                    detail=f"Highest: {top.heading} — {str(top.finding).lower()}"
                           + (f" · needs {top.triggered_rung.replace('_', ' ')}" if top.triggered_rung and top.triggered_rung != "none" else "")
                           + (f" · risk {band}" if band else ""),
                    severity=sev,
                    actions=[Action("review", f"Review {len(pending)} →", True), Action("open", "Open matter")],
                    meta={"pending": len(pending), "risk_band": band},
                ))
                continue
            # 3) cleared and ready to send for signature
            if r.state == RequestState.APPROVED:
                out.append(Decision(
                    id=f"ready_to_send:{r.id}", kind="ready_to_send", request_id=r.id, ref=r.ref,
                    title=cp, actor="Pipeline",
                    headline="Cleared to send — ladder cleared, every redline decided",
                    detail="The decisions-applied counter-proposal is ready to go out for signature.",
                    severity="warn",
                    actions=[Action("send", "Send for signature", True), Action("open", "Open matter")],
                    meta={},
                ))
                continue

    # 4) renewals due (from the contract registry — expiring soon, not yet renewed)
    reg = contract_registry(db, user.org_id)
    readable_ids = {r.id for r in reqs}
    for row in reg.get("rows", []):
        if row.get("status") == "expiring" and row["id"] in readable_ids:
            days = row.get("days_left")
            out.append(Decision(
                id=f"renewal:{row['id']}", kind="renewal", request_id=row["id"], ref=row["ref"],
                title=row.get("counterparty", ""), actor="Pipeline",
                headline=f"Expires in {days} day{'s' if days != 1 else ''} — renew?",
                detail=f"{row.get('nda_type', '')} · executed contract reaching end of term.",
                severity="warn" if (days is not None and days <= 14) else "normal",
                actions=[Action("renew", "Renew", True), Action("open", "Open matter")],
                meta={"days_left": days},
            ))

    out.sort(key=lambda d: (_SEV_RANK.get(d.severity, 3), d.ref), reverse=False)
    return out


def _cp_name(db: Session, r) -> str:
    from ..models import Counterparty
    cp = db.get(Counterparty, r.counterparty_id)
    return cp.name if cp else ""


def _risk_band(db: Session, r) -> str | None:
    from ..services.risk import assessment_history
    h = assessment_history(db, r.id)
    return h[-1].band.value if h else None


def summarize(decisions: list[Decision]) -> dict:
    """Counts for the Daily-brief strip atop the feed."""
    by_kind: dict[str, int] = {}
    for d in decisions:
        by_kind[d.kind] = by_kind.get(d.kind, 0) + 1
    return {
        "total": len(decisions),
        "critical": sum(1 for d in decisions if d.severity == "critical"),
        "by_kind": by_kind,
    }


def payload(decisions: list[Decision]) -> list[dict]:
    return [asdict(d) for d in decisions]

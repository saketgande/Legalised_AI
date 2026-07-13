"""Intake triage — the fork that makes self-serve possible.

Given a freshly-created outbound NDA request, decide which lane it takes:

* ``AUTO``     — golden path: within policy, no lawyer touches it.
* ``ASSISTED`` — something needs sign-off; build an approval ladder.
* ``ESCALATED``— a hard blocker (blocklisted / sanctioned counterparty).

The rules are deterministic and explainable — every decision returns the
reasons it fired, which the Cockpit surfaces so a legal-ops admin can trust
(and later tune) the automation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config import settings
from ..models import Counterparty, Lane, Request


@dataclass
class TriageResult:
    lane: Lane
    reasons: list[str] = field(default_factory=list)


def triage_outbound(request: Request, counterparty: Counterparty) -> TriageResult:
    reasons: list[str] = []

    if counterparty.sanctioned:
        return TriageResult(Lane.ESCALATED, ["counterparty is sanctioned — hard block"])
    if counterparty.blocklisted:
        return TriageResult(Lane.ESCALATED, ["counterparty is on the blocklist"])

    blockers: list[str] = []

    if request.purpose in settings.auto_allowed_purposes:
        reasons.append(f"purpose '{request.purpose}' is pre-approved for self-serve")
    else:
        blockers.append(f"purpose '{request.purpose}' needs legal review")

    if request.jurisdiction in settings.auto_allowed_jurisdictions:
        reasons.append(f"jurisdiction '{request.jurisdiction}' is in the approved set")
    else:
        blockers.append(f"jurisdiction '{request.jurisdiction}' is outside the approved set")

    if request.term_months <= settings.auto_max_term_months:
        reasons.append(f"term {request.term_months}mo within {settings.auto_max_term_months}mo cap")
    else:
        blockers.append(
            f"term {request.term_months}mo exceeds the {settings.auto_max_term_months}mo self-serve cap"
        )

    reasons.append("outbound on our standard paper")

    if blockers:
        return TriageResult(Lane.ASSISTED, blockers)
    return TriageResult(Lane.AUTO, reasons)

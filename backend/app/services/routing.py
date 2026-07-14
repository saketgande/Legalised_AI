"""Routing rules — the admin-editable brain that runs after classification.

Ordered WHEN -> THEN rows. All non-null conditions must match (AND); actions
apply in rule order; a rule with ``stop_on_match`` halts evaluation. Every
fired rule writes an audit row AND appends a which-rule-fired line to the
request's triage reasons — explainability is the product, per the triage
engine's own ethos.

``preview_rule`` is the dry-run: evaluate candidate conditions against the org's
recent requests without mutating anything, so a legal-ops admin can see "this
would have matched 12 of the last 50" before activating.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    ActorType, Counterparty, Lane, Request, RequestPriority, RoutingRule, User,
)
from .audit import record_audit

_PRIORITIES = {p.value for p in RequestPriority}


def _matches(rule: RoutingRule, r: Request, counterparty_name: str) -> bool:
    if rule.match_type_key and rule.match_type_key.lower() != (r.type or "").lower():
        return False
    if rule.match_direction and rule.match_direction != r.direction.value:
        return False
    if rule.match_jurisdiction and rule.match_jurisdiction.lower() != (r.jurisdiction or "").lower():
        return False
    if rule.match_keyword:
        haystack = " ".join(filter(None, [
            counterparty_name, r.purpose or "", r.details or "",
        ])).lower()
        if rule.match_keyword.lower() not in haystack:
            return False
    return True


def _describe_actions(rule: RoutingRule, assignee: User | None) -> list[str]:
    acts: list[str] = []
    if assignee is not None:
        acts.append(f"assign to {assignee.name}")
    if rule.set_priority in _PRIORITIES:
        acts.append(f"priority {rule.set_priority.lower()}")
    if rule.set_sla_hours:
        acts.append(f"SLA {rule.set_sla_hours}h")
    if rule.escalate:
        acts.append("escalate")
    return acts


def apply_routing_rules(db: Session, r: Request) -> list[str]:
    """Evaluate the org's active rules in order against ``r``, applying actions.
    Returns human-readable 'Rule X: did Y' lines (also appended to
    triage_reasons and audited per fired rule). Errors propagate: a mutation
    silently persisted without its audit row would be worse than a failed
    intake, and a flush failure poisons the session for the caller anyway."""
    fired: list[str] = []
    cp = db.get(Counterparty, r.counterparty_id)
    cp_name = cp.name if cp else ""
    rules = db.execute(
        select(RoutingRule)
        .where(RoutingRule.org_id == r.org_id, RoutingRule.active == True)  # noqa: E712
        .order_by(RoutingRule.ordinal.asc(), RoutingRule.created_at.asc())
    ).scalars().all()

    for rule in rules:
        if not _matches(rule, r, cp_name):
            continue
        assignee = db.get(User, rule.set_assignee_user_id) if rule.set_assignee_user_id else None
        # re-validate at FIRE time: the assignee may have been suspended (or the
        # rule row hand-edited) since the rule was written — never auto-assign
        # work to someone who cannot log in
        if assignee is not None and (assignee.suspended or assignee.org_id != r.org_id):
            assignee = None
        if assignee is not None:
            r.assigned_to_user_id = assignee.id
        if rule.set_priority in _PRIORITIES:
            r.priority = RequestPriority(rule.set_priority)
        if rule.set_sla_hours:
            r.sla_target_hours = rule.set_sla_hours
        if rule.escalate:
            r.lane = Lane.ESCALATED
        acts = _describe_actions(rule, assignee)
        if rule.set_assignee_user_id and assignee is None:
            acts.append("assignee skipped (suspended or missing)")
        line = f"Routing rule '{rule.name}': {', '.join(acts) if acts else 'matched (no actions)'}"
        fired.append(line)
        record_audit(
            db, org_id=r.org_id, action="routing.rule.fired", resource_type="Request",
            resource_id=r.id, actor_type=ActorType.SYSTEM, actor_label="Routing Engine",
            metadata={"rule_id": rule.id, "rule_name": rule.name, "actions": acts},
        )
        if rule.stop_on_match:
            break

    if fired:
        r.triage_reasons = list(r.triage_reasons or []) + fired
    return fired


def preview_rule(db: Session, org_id: str, conditions: dict, limit: int = 50) -> dict:
    """Dry-run: which of the org's most recent requests would these conditions
    match? Read-only — builds a transient rule and evaluates it."""
    rule = RoutingRule(
        org_id=org_id, name="(preview)",
        match_type_key=conditions.get("match_type_key") or None,
        match_direction=conditions.get("match_direction") or None,
        match_keyword=conditions.get("match_keyword") or None,
        match_jurisdiction=conditions.get("match_jurisdiction") or None,
    )
    recent = db.execute(
        select(Request).where(Request.org_id == org_id)
        .order_by(Request.created_at.desc()).limit(limit)
    ).scalars().all()
    matches = []
    for r in recent:
        cp = db.get(Counterparty, r.counterparty_id)
        if _matches(rule, r, cp.name if cp else ""):
            matches.append({
                "ref": r.ref, "type": r.type, "counterparty": cp.name if cp else "—",
                "state": r.state.value, "created_at": r.created_at.isoformat(),
            })
    return {"evaluated": len(recent), "matched": len(matches), "matches": matches[:20]}

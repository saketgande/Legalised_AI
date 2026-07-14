"""Workflow templates + the stage executor — the ladder as data.

Three layers, mirroring the design mockup:

* **Rung library** (code): the canonical stage keys every contract walks —
  intake, classify, draft, redline, risk_score, approvals, counterparty,
  esign, obligations, seal — plus H-kind *gate* rungs a template can add
  (always or conditionally) which feed extra steps into every round's
  approval ladder.
* **Templates** (data): per-type, versioned, one active default per type.
  Pinned rungs can move but never leave; publish bumps the version and
  applies to NEW matters only.
* **Instances**: at creation the template is evaluated against the matter's
  attributes (conditions fire or stay dormant — both audited) and the rung
  snapshot is pinned onto the request. ``mark_stage`` advances it from the
  same chokepoints the state machine already runs through, accumulating
  time-at-stage per rung.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import ActorType, Request, RequestState, WorkflowTemplate
from .audit import record_audit

KINDS = ("D", "A", "H", "T")
GATE_RUNGS = ("vp_legal", "gc")
COND_FIELDS = {
    "jurisdiction_foreign": "Governing law outside the approved set",
    "new_counterparty": "First contract with this counterparty",
    "term_over": "Term exceeds N months",
    "inbound_paper": "Their paper (inbound review)",
}

# canonical stage spine, in order. Templates may omit optional stages and add
# gate_* rungs anywhere between classify and approvals.
STAGE_ORDER = ["intake", "classify", "draft", "redline", "risk_score",
               "approvals", "counterparty", "esign", "obligations", "seal"]
PINNED_ALWAYS = {"intake", "seal"}  # can never be removed from a template

_LIB = {
    "intake":       ("D", "Intake & classification", "One normalized ticket from any channel."),
    "classify":     ("D", "Type & routing", "Contract type resolved; routing rules evaluated."),
    "draft":        ("A", "Draft from playbook", "Assembled from preferred clauses — never free-generated."),
    "redline":      ("A", "Redline & findings", "Clause-by-clause against the playbook; every finding stays PENDING until a human decides."),
    "risk_score":   ("D", "AI risk score", "Deterministic factor core; AI may only raise severity."),
    "approvals":    ("H", "Approval ladder", "Rungs picked by the risk band via the type's matrix."),
    "counterparty": ("T", "Counterparty negotiation", "Their review; returns loop back through redline + score."),
    "esign":        ("T", "Execution — e-signature", "Both signatories; completion via webhook."),
    "obligations":  ("D", "Obligation extraction", "Renewals, survival, return duties → live timers."),
    "seal":         ("D", "Filed & sealed", "Registry row, renewal clock, chain-sealed."),
}


def default_rungs(type_key: str) -> list[dict]:
    """The canonical spine as a template. DPA (regulated data) additionally
    carries a DPO gate that adds a counsel step to every round's ladder."""
    rungs = []
    for key in STAGE_ORDER:
        kind, name, desc = _LIB[key]
        rungs.append({
            "key": key, "kind": kind, "name": name, "desc": desc,
            "mode": "pinned" if key in PINNED_ALWAYS else "always",
        })
    if type_key == "dpa":
        gate = {
            "key": "gate_dpo", "kind": "H", "name": "DPO review — regulated data",
            "desc": "Processing personal data: the privacy gate joins every round's ladder.",
            "mode": "always", "rung": "vp_legal",
        }
        rungs.insert(STAGE_ORDER.index("approvals"), gate)
    return rungs


def validate_rungs(rungs: list) -> list[str]:
    """Problems list (empty = valid). Ordering constraints keep the designer
    from building nonsense (esign before drafting, seal in the middle)."""
    problems: list[str] = []
    if not isinstance(rungs, list) or not rungs:
        return ["rungs must be a non-empty list"]
    keys = [r.get("key") for r in rungs]
    if len(set(keys)) != len(keys):
        problems.append("duplicate rung keys")
    for need in PINNED_ALWAYS:
        if need not in keys:
            problems.append(f"pinned rung '{need}' cannot be removed")
    for r in rungs:
        if r.get("kind") not in KINDS:
            problems.append(f"rung '{r.get('key')}': unknown kind '{r.get('kind')}'")
        if not str(r.get("key") or "").strip() or not str(r.get("name") or "").strip():
            problems.append("every rung needs a key and a name")
        mode = r.get("mode")
        if mode not in ("pinned", "always", "cond"):
            problems.append(f"rung '{r.get('key')}': unknown mode '{mode}'")
        if mode == "cond":
            cond = r.get("cond") or {}
            if cond.get("field") not in COND_FIELDS:
                problems.append(f"rung '{r.get('key')}': unknown condition '{cond.get('field')}'")
            if cond.get("field") == "term_over" and not isinstance(cond.get("value"), (int, float)):
                problems.append(f"rung '{r.get('key')}': term_over needs a numeric value")
        if r.get("kind") == "H" and str(r.get("key", "")).startswith("gate_") \
                and r.get("rung") not in GATE_RUNGS:
            problems.append(f"gate rung '{r.get('key')}' needs rung vp_legal or gc")
    # ordering: canonical stages must appear in canonical order
    canon = [k for k in keys if k in STAGE_ORDER]
    if canon != sorted(canon, key=STAGE_ORDER.index):
        problems.append("canonical stages are out of order "
                        f"(must follow {' → '.join(STAGE_ORDER)})")
    if keys and keys[0] != "intake":
        problems.append("intake must be the first rung")
    if keys and keys[-1] != "seal":
        problems.append("seal must be the last rung")
    return problems


def ensure_default_workflows(db: Session, org_id: str) -> None:
    """Seed one active default template per CONTRACT type (idempotent)."""
    from .request_types import list_types
    from ..models import RequestCategory

    existing = {
        (t.type_key) for t in db.execute(
            select(WorkflowTemplate).where(WorkflowTemplate.org_id == org_id)
        ).scalars().all()
    }
    for rt in list_types(db, org_id, active_only=False):
        if rt.category != RequestCategory.CONTRACT or rt.key in existing:
            continue
        db.add(WorkflowTemplate(
            org_id=org_id, type_key=rt.key, name=f"{rt.label} — standard flow",
            version=1, active=True, rungs=default_rungs(rt.key),
        ))


def active_template(db: Session, org_id: str, type_key: str) -> WorkflowTemplate | None:
    return db.execute(
        select(WorkflowTemplate).where(
            WorkflowTemplate.org_id == org_id,
            WorkflowTemplate.type_key == (type_key or "nda").lower(),
            WorkflowTemplate.active == True,  # noqa: E712
        )
    ).scalars().first()


# ————————————————————— instantiation —————————————————————
def _matter_attrs(db: Session, r: Request) -> dict:
    from ..models import Direction

    prior = db.execute(
        select(Request.id).where(
            Request.org_id == r.org_id,
            Request.counterparty_id == r.counterparty_id,
            Request.id != r.id,
            Request.state.in_([RequestState.EXECUTED, RequestState.FILED]),
        )
    ).scalars().first()
    return {
        "jurisdiction_foreign": r.jurisdiction not in settings.auto_allowed_jurisdictions,
        "new_counterparty": prior is None,
        "term_months": r.term_months or 0,
        "inbound_paper": r.direction == Direction.INBOUND,
    }


def _cond_fires(cond: dict, attrs: dict) -> bool:
    field = cond.get("field")
    if field == "term_over":
        return attrs.get("term_months", 0) > float(cond.get("value") or 0)
    return bool(attrs.get(field))


def instantiate_workflow(db: Session, r: Request) -> None:
    """Evaluate the active template against this matter's attributes and pin
    the rung snapshot. Fired AND dormant rules both land on the ledger — the
    audit answers 'why is this step here / why isn't it'."""
    tpl = active_template(db, r.org_id, (r.type or "nda").lower())
    if tpl is None:
        return  # pre-slice-4 org or unseeded type: state machine still governs
    attrs = _matter_attrs(db, r)
    rungs, fired, dormant = [], [], []
    for tr in (tpl.rungs or []):
        if tr.get("mode") == "cond":
            if _cond_fires(tr.get("cond") or {}, attrs):
                fired.append(tr.get("cond", {}).get("label") or tr.get("name"))
            else:
                dormant.append(tr.get("cond", {}).get("label") or tr.get("name"))
                continue
        rungs.append({
            "key": tr["key"], "kind": tr["kind"], "name": tr["name"],
            "desc": tr.get("desc", ""), "mode": tr.get("mode", "always"),
            "rung": tr.get("rung"), "sla_hours": tr.get("sla_hours"),
            "status": "waiting", "started_at": None, "completed_at": None,
            "spent_seconds": 0, "round": None,
        })
    r.workflow_template_id = tpl.id
    r.workflow_version = tpl.version
    r.workflow_rungs = rungs
    record_audit(
        db, org_id=r.org_id, action="workflow.instantiated", resource_type="Request",
        resource_id=r.id, actor_type=ActorType.SYSTEM, actor_label="Workflow Engine",
        metadata={"template": tpl.name, "version": tpl.version,
                  "rungs": [x["key"] for x in rungs],
                  "rules_fired": fired, "rules_dormant": dormant},
    )


def gate_ladder_rungs(r: Request) -> list[dict]:
    """The template's H-kind gate rungs, as extra approval-ladder steps for
    every round: [{rung, reason}]."""
    out = []
    for rung in (r.workflow_rungs or []):
        if rung.get("kind") == "H" and str(rung.get("key", "")).startswith("gate_") \
                and rung.get("rung"):
            out.append({"rung": rung["rung"], "reason": rung.get("name", "Workflow gate")})
    return out


# ————————————————————— the executor —————————————————————
def _now() -> datetime:
    return datetime.now(timezone.utc)


def mark_stage(db: Session, r: Request, key: str, status: str = "done",
               *, round_no: int | None = None) -> None:
    """Advance one rung of the instance snapshot. Tolerant by design: matters
    created before slice 4 (empty snapshot) and templates without the stage
    are silent no-ops — the executor mirrors the state machine, it doesn't
    gate it. Re-activating a done rung (negotiation loops) accumulates time."""
    # deep-copy the rung dicts: mutating the originals in place would ALSO
    # mutate SQLAlchemy's committed-state snapshot, making the change invisible
    # to flush (old == new) and silently dropping the update
    rungs = [dict(x) for x in (r.workflow_rungs or [])]
    if not rungs:
        return
    changed = False
    for rung in rungs:
        if rung.get("key") != key:
            continue
        now_iso = _now().isoformat()
        if status == "active":
            if rung.get("status") != "active":
                rung["status"] = "active"
                rung["started_at"] = now_iso
                if round_no:
                    rung["round"] = round_no
                changed = True
        elif status == "done":
            if rung.get("status") == "active" and rung.get("started_at"):
                try:
                    started = datetime.fromisoformat(rung["started_at"])
                    rung["spent_seconds"] = int(rung.get("spent_seconds") or 0) + \
                        max(0, int((_now() - started).total_seconds()))
                except (ValueError, TypeError):
                    pass
            rung["status"] = "done"
            rung["completed_at"] = now_iso
            if round_no:
                rung["round"] = round_no
            changed = True
        elif status == "waiting":
            rung["status"] = "waiting"
            changed = True
        break
    if changed:
        r.workflow_rungs = rungs  # JSON column: reassign so the ORM sees it


def mark_stages(db: Session, r: Request, *keys: str, status: str = "done",
                round_no: int | None = None) -> None:
    for key in keys:
        mark_stage(db, r, key, status, round_no=round_no)

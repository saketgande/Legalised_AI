"""Workflow-template regressions: validation constraints, conditional
instantiation with fired/dormant audit, gate rungs feeding the ladder,
executor stage marks through the full loop, and version pinning."""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    ActorType,
    ApprovalLadder,
    AuditEvent,
    Organization,
    Person,
    Playbook,
    PlaybookRule,
    RequestCategory,
    RequestState,
    RequestType,
    WorkflowTemplate,
)
from app.services.intake import Actor, create_outbound
from app.services.negotiation import record_counterparty_return, send_to_counterparty
from app.services.workflows import (
    default_rungs,
    ensure_default_workflows,
    instantiate_workflow,
    validate_rungs,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _org(db, with_dpa_type=False):
    org = Organization(name="T"); db.add(org); db.flush()
    db.add(RequestType(org_id=org.id, key="nda", label="NDA / confidentiality", description="",
                       category=RequestCategory.CONTRACT, default_sla_hours=8, ordinal=1))
    if with_dpa_type:
        db.add(RequestType(org_id=org.id, key="dpa", label="DPA / data processing", description="",
                           category=RequestCategory.CONTRACT, default_sla_hours=24, ordinal=2))
    pb = Playbook(org_id=org.id, name="Std", version=1, active=True); db.add(pb); db.flush()
    db.add(PlaybookRule(playbook_id=pb.id, rule_key="TERM-01", clause_type="term", heading="Term",
                        preferred_body="Lasts {{hold.term_months}} months.", ordinal=1,
                        mandatory=True, deviation_rung="vp_legal"))
    p = Person(org_id=org.id, name="R", email="r@t.example"); db.add(p); db.flush()
    ensure_default_workflows(db, org.id)
    db.flush()
    return org, p


ACTOR = Actor(None, ActorType.SYSTEM, "t")


# ————————————————— validation —————————————————
def test_default_rungs_validate():
    assert validate_rungs(default_rungs("nda")) == []
    assert validate_rungs(default_rungs("dpa")) == []


def test_pinned_rungs_cannot_be_removed():
    rungs = [r for r in default_rungs("nda") if r["key"] != "seal"]
    assert any("seal" in p for p in validate_rungs(rungs))


def test_canonical_order_enforced():
    rungs = default_rungs("nda")
    i, j = 2, 7  # draft <-> esign swap = nonsense ladder
    rungs[i], rungs[j] = rungs[j], rungs[i]
    assert any("order" in p for p in validate_rungs(rungs))


def test_gate_rung_needs_valid_rung():
    rungs = default_rungs("nda")
    rungs.insert(5, {"key": "gate_x", "kind": "H", "name": "X gate", "mode": "always",
                     "rung": "ceo"})
    assert any("gate_x" in p for p in validate_rungs(rungs))


def test_cond_needs_known_field():
    rungs = default_rungs("nda")
    rungs.insert(5, {"key": "gate_y", "kind": "H", "name": "Y", "mode": "cond",
                     "rung": "gc", "cond": {"field": "moon_phase"}})
    assert any("moon_phase" in str(p) for p in validate_rungs(rungs))


# ————————————————— instantiation —————————————————
def test_instantiation_pins_snapshot_and_audits_rules(db):
    org, p = _org(db)
    tpl = db.execute(select(WorkflowTemplate).where(
        WorkflowTemplate.org_id == org.id, WorkflowTemplate.type_key == "nda")).scalars().first()
    # add a conditional gate that will NOT fire (term_over 100)
    rungs = list(tpl.rungs)
    rungs.insert(5, {"key": "gate_term", "kind": "H", "name": "Long-term gate", "mode": "cond",
                     "rung": "gc", "cond": {"field": "term_over", "value": 100,
                                            "label": "Term over 100 months"}})
    tpl.rungs = rungs
    db.flush()

    r = create_outbound(db, org=org.id, requester=p, actor=ACTOR,
                        counterparty_name="Acme", purpose="sales_evaluation",
                        jurisdiction="US", term_months=12)
    keys = [x["key"] for x in (r.workflow_rungs or [])]
    assert "gate_term" not in keys                # dormant condition
    assert r.workflow_version == tpl.version      # pinned
    ev = db.execute(select(AuditEvent).where(
        AuditEvent.resource_id == r.id, AuditEvent.action == "workflow.instantiated"
    )).scalars().first()
    assert ev is not None
    assert "Term over 100 months" in (ev.metadata_json.get("rules_dormant") or [])


def test_gate_rung_joins_every_rounds_ladder(db):
    org, p = _org(db, with_dpa_type=True)
    # give the org a DPA playbook so drafting works
    dpa_pb = Playbook(org_id=org.id, name="DPA std", version=1, active=True,
                      contract_type_key="dpa")
    db.add(dpa_pb); db.flush()
    db.add(PlaybookRule(playbook_id=dpa_pb.id, rule_key="SEC-01", clause_type="security_measures",
                        heading="Security Measures", preferred_body="Keep it safe.",
                        ordinal=1, mandatory=True, deviation_rung="vp_legal"))
    db.flush()
    r = create_outbound(db, org=org.id, requester=p, actor=ACTOR,
                        counterparty_name="CloudVendor", purpose="vendor_evaluation",
                        jurisdiction="US", term_months=12, type_key="dpa")
    # the DPA default template carries gate_dpo -> a vp_legal step with the DPO reason
    ladder = db.execute(select(ApprovalLadder).where(ApprovalLadder.request_id == r.id)).scalars().first()
    assert ladder is not None
    reasons = " ".join(s.reason for s in ladder.steps)
    assert "DPO review" in reasons


def test_executor_marks_full_loop(db):
    org, p = _org(db)
    r = create_outbound(db, org=org.id, requester=p, actor=ACTOR,
                        counterparty_name="Acme", purpose="sales_evaluation",
                        jurisdiction="US", term_months=12)
    assert r.state == RequestState.APPROVED
    by_key = {x["key"]: x for x in r.workflow_rungs}
    assert by_key["intake"]["status"] == "done"
    assert by_key["draft"]["status"] == "done"
    assert by_key["risk_score"]["status"] == "done"
    assert by_key["approvals"]["status"] == "done"   # AUTO lane
    assert by_key["counterparty"]["status"] == "waiting"

    r = send_to_counterparty(db, r, ACTOR)
    by_key = {x["key"]: x for x in r.workflow_rungs}
    assert by_key["counterparty"]["status"] == "active"

    r = record_counterparty_return(db, r, body_text=(
        "1. Term\nThis Agreement shall remain in effect for sixty (60) months.\n"), actor=ACTOR)
    by_key = {x["key"]: x for x in r.workflow_rungs}
    assert by_key["counterparty"]["status"] == "done"
    assert by_key["redline"]["status"] == "done" and by_key["redline"]["round"] == 2
    assert by_key["approvals"]["status"] == "active"  # round-2 ladder pending


def test_publish_does_not_rewrite_inflight(db):
    org, p = _org(db)
    r = create_outbound(db, org=org.id, requester=p, actor=ACTOR,
                        counterparty_name="Acme", purpose="sales_evaluation",
                        jurisdiction="US", term_months=12)
    v_at_creation = r.workflow_version
    tpl = db.execute(select(WorkflowTemplate).where(
        WorkflowTemplate.org_id == org.id, WorkflowTemplate.type_key == "nda")).scalars().first()
    tpl.version += 1  # publish
    db.flush()
    db.refresh(r)
    assert r.workflow_version == v_at_creation  # pinned snapshot, not live


def test_no_template_is_a_silent_noop(db):
    """Matters in orgs without templates keep working — executor never gates."""
    org = Organization(name="Bare"); db.add(org); db.flush()
    db.add(RequestType(org_id=org.id, key="nda", label="NDA", description="",
                       category=RequestCategory.CONTRACT, default_sla_hours=8, ordinal=1))
    pb = Playbook(org_id=org.id, name="Std", version=1, active=True); db.add(pb); db.flush()
    db.add(PlaybookRule(playbook_id=pb.id, rule_key="T", clause_type="term", heading="Term",
                        preferred_body="12 months.", ordinal=1))
    p = Person(org_id=org.id, name="R", email="r2@t.example"); db.add(p); db.flush()
    r = create_outbound(db, org=org.id, requester=p, actor=ACTOR,
                        counterparty_name="Acme", purpose="sales_evaluation",
                        jurisdiction="US", term_months=12)
    assert r.workflow_rungs in ([], None)
    assert r.state == RequestState.APPROVED  # loop unaffected

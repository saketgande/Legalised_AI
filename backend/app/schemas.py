"""API request/response shapes."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


# ————————————————————————— inbound —————————————————————————
class CreateRequestIn(BaseModel):
    # requester is now the authenticated user; these are accepted but ignored
    requester_name: str | None = None
    requester_email: str | None = None
    counterparty_name: str
    nda_type: str = "MUTUAL"          # MUTUAL | ONE_WAY
    purpose: str = "sales_evaluation"
    jurisdiction: str = "US"
    term_months: int = 24
    channel: str = "FORM"
    playbook_id: str | None = None    # null = the org's default playbook


class ApproveStepIn(BaseModel):
    user_id: str | None = None
    note: str | None = None


class CreateInboundIn(BaseModel):
    counterparty_name: str
    nda_type: str = "MUTUAL"
    purpose: str = "vendor_evaluation"
    requester_name: str = "Sam Carter"
    requester_email: str = "sam.carter@northwind.example"
    body_text: str
    playbook_id: str | None = None    # null = the org's default playbook


class DecideChangeIn(BaseModel):
    action: str                            # "approve" | "reject" | "edit"
    user_id: str | None = None
    edited_after_text: str | None = None   # required when action == "edit"


# ————————————————————————— outbound —————————————————————————
class ClauseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    ordinal: int
    section_no: str
    clause_type: str | None
    heading: str
    body_text: str
    source_rule_key: str | None


class DocumentOut(BaseModel):
    id: str
    title: str
    origin: str
    version_no: int
    content_hash: str
    body_markdown: str
    clauses: list[ClauseOut]


class ApprovalStepOut(BaseModel):
    id: str
    ordinal: int
    rung: str
    reason: str
    status: str
    assignee_name: str | None
    decided_by: str | None
    decided_at: datetime | None


class LadderOut(BaseModel):
    id: str
    status: str
    steps: list[ApprovalStepOut]


class TimelineEventOut(BaseModel):
    chain_position: int
    action: str
    actor_type: str
    actor_label: str
    metadata: dict
    created_at: datetime


class RequestSummaryOut(BaseModel):
    id: str
    ref: str
    type: str
    direction: str
    nda_type: str
    state: str
    lane: str | None
    counterparty_name: str
    requester_name: str
    purpose: str
    jurisdiction: str
    term_months: int
    created_at: datetime
    open_steps: int
    playbook_id: str | None = None
    playbook_name: str | None = None
    playbook_version: int | None = None
    esign_provider: str | None = None
    esign_status: str | None = None
    esign_envelope_id: str | None = None


class ProposedChangeOut(BaseModel):
    id: str
    ordinal: int
    section_no: str
    heading: str
    finding: str
    rule_key: str | None
    before_text: str
    after_text: str
    rationale: str
    checks: list[dict]
    confidence: float | None
    triggered_rung: str
    decision: str


class ReviewOut(BaseModel):
    id: str
    status: str
    summary: dict
    changes: list[ProposedChangeOut]
    counter_markdown: str
    required_rungs: list[str]


class RequestDetailOut(RequestSummaryOut):
    triage_reasons: list[str]
    document: DocumentOut | None
    ladder: LadderOut | None
    review: ReviewOut | None
    timeline: list[TimelineEventOut]


class RequesterStatusOut(BaseModel):
    ref: str
    counterparty_name: str
    nda_type: str
    purpose: str
    stage: str            # friendly stage label
    stage_index: int      # 0..4
    needs_you: bool
    headline: str
    detail: str
    document_ready: bool
    expires_at: str | None = None   # renewal clock, once executed
    timeline: list[TimelineEventOut]

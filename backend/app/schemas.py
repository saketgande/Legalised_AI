"""API request/response shapes."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ————————————————————————— inbound —————————————————————————
class CreateRequestIn(BaseModel):
    # requester is now the authenticated user; these are accepted but ignored
    requester_name: str | None = None
    requester_email: str | None = None
    counterparty_name: str
    nda_type: str = "MUTUAL"          # MUTUAL | ONE_WAY
    purpose: str = "sales_evaluation"
    jurisdiction: str = "US"
    term_months: int = Field(24, ge=1, le=120)  # 0/blank would draft a nonsense term
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


class CreateAdviceIn(BaseModel):
    type_key: str                          # a request-type catalog key (ADVICE category)
    question: str
    urgency: str = "NORMAL"                # RequestPriority value
    channel: str = "FORM"


class AssignIn(BaseModel):
    user_id: str | None = None             # null = unassign


class SnoozeIn(BaseModel):
    hours: int | None = None               # null = unsnooze


class ResolveAdviceIn(BaseModel):
    answer: str                            # the approved/edited answer text


class BulkActionIn(BaseModel):
    ids: list[str]
    action: str                            # "assign" | "snooze" | "unsnooze"
    user_id: str | None = None             # for assign
    hours: int | None = None               # for snooze


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
    type_label: str | None = None      # catalog label ("Legal question")
    category: str = "CONTRACT"         # CONTRACT | ADVICE (which engine)
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
    priority: str = "NORMAL"
    assigned_to_user_id: str | None = None
    assigned_to_name: str | None = None
    snoozed_until: datetime | None = None
    sla_target_hours: int | None = None
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
    details: str | None = None            # the ADVICE ask
    resolution_draft: str | None = None   # agent's PENDING answer proposal
    resolution_note: str | None = None    # the approved answer


class RequesterStatusOut(BaseModel):
    ref: str
    counterparty_name: str
    nda_type: str
    purpose: str
    stage: str            # friendly stage label
    stage_index: int      # index into ``stages``
    stages: list[str] | None = None  # per-engine tracker labels; null = NDA default
    needs_you: bool
    headline: str
    detail: str
    document_ready: bool
    answer: str | None = None       # the approved advice answer, once resolved
    expires_at: str | None = None   # renewal clock, once executed
    timeline: list[TimelineEventOut]

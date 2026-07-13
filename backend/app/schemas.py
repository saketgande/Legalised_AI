"""API request/response shapes."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


# ————————————————————————— inbound —————————————————————————
class CreateRequestIn(BaseModel):
    requester_name: str
    requester_email: str
    counterparty_name: str
    nda_type: str = "MUTUAL"          # MUTUAL | ONE_WAY
    purpose: str = "sales_evaluation"
    jurisdiction: str = "US"
    term_months: int = 24
    channel: str = "FORM"


class ApproveStepIn(BaseModel):
    user_id: str | None = None
    note: str | None = None


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


class RequestDetailOut(RequestSummaryOut):
    triage_reasons: list[str]
    document: DocumentOut | None
    ladder: LadderOut | None
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
    timeline: list[TimelineEventOut]

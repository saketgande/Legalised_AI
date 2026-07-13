"""Domain model for the NDA wedge.

One ``Request`` is the spine. Everything hangs off it: the structured document
(so redlines are addressable later), the playbook it was drafted from, the
approval ladder assembled from policy, and an append-only, hash-chained audit
log. This is the "one brain" — intake and CLM read the same rows.

The walking skeleton implements the OUTBOUND golden path (we draft our paper).
Inbound third-party review (ReviewRun / ProposedChange) is the next slice and
is intentionally not modelled yet.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ————————————————————————————— enums —————————————————————————————
class RequestState(str, enum.Enum):
    NEW = "NEW"
    CLASSIFIED = "CLASSIFIED"
    ROUTED = "ROUTED"
    DRAFTED = "DRAFTED"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    OUT_FOR_SIGNATURE = "OUT_FOR_SIGNATURE"
    EXECUTED = "EXECUTED"
    FILED = "FILED"
    CANCELLED = "CANCELLED"


class Lane(str, enum.Enum):
    AUTO = "AUTO"          # golden path: no lawyer touches it
    ASSISTED = "ASSISTED"  # one or more approvals required
    ESCALATED = "ESCALATED"


class Direction(str, enum.Enum):
    OUTBOUND = "OUTBOUND"  # we draft and send our paper
    INBOUND = "INBOUND"    # counterparty sent their paper (future slice)


class NdaType(str, enum.Enum):
    MUTUAL = "MUTUAL"
    ONE_WAY = "ONE_WAY"


class OurRole(str, enum.Enum):
    DISCLOSER = "DISCLOSER"
    RECIPIENT = "RECIPIENT"
    BOTH = "BOTH"


class ActorType(str, enum.Enum):
    USER = "USER"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"


class StepStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"


# ———————————————————————— shared entities ————————————————————————
class Organization(Base):
    __tablename__ = "organization"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    """Internal legal / admin users (reviewers, approvers) + requesters."""
    __tablename__ = "app_user"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organization.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default="attorney")
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Person(Base):
    """Humans who are not internal legal staff — requesters, counterparty contacts."""
    __tablename__ = "person"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organization.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)
    department: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Counterparty(Base):
    __tablename__ = "counterparty"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organization.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    domain: Mapped[str | None] = mapped_column(String, nullable=True)
    blocklisted: Mapped[bool] = mapped_column(Boolean, default=False)
    sanctioned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ————————————————————————————— playbook —————————————————————————————
class Playbook(Base):
    __tablename__ = "playbook"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organization.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    rules: Mapped[list[PlaybookRule]] = relationship(back_populates="playbook")


class PlaybookRule(Base):
    """A clause position, authored in natural language, with structured params
    the deterministic checkers use and the approval rung a deviation triggers.
    In the outbound path we assemble the ``preferred_body`` clauses into a draft;
    in the inbound path (next slice) we compare counterparty paper against these.
    """
    __tablename__ = "playbook_rule"
    __table_args__ = (UniqueConstraint("playbook_id", "rule_key", name="uq_playbook_rule_key"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    playbook_id: Mapped[str] = mapped_column(ForeignKey("playbook.id"), nullable=False)
    rule_key: Mapped[str] = mapped_column(String, nullable=False)  # "LoL-02" — the citation target
    clause_type: Mapped[str] = mapped_column(String, nullable=False)  # "limitation_of_liability"
    heading: Mapped[str] = mapped_column(String, nullable=False)  # "Limitation of Liability"
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    applies_when: Mapped[dict] = mapped_column(JSON, default=dict)  # {ndaType?, ourRole?}
    preferred_body: Mapped[str] = mapped_column(Text, nullable=False)  # clause text w/ {{vars}}
    preferred_position: Mapped[str] = mapped_column(Text, default="")
    structured_params: Mapped[dict] = mapped_column(JSON, default=dict)
    mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    deviation_rung: Mapped[str] = mapped_column(String, default="none")  # gc | vp_legal | requesting_manager | none
    rationale: Mapped[str] = mapped_column(Text, default="")
    playbook: Mapped[Playbook] = relationship(back_populates="rules")


# ————————————————————————— the spine: Request —————————————————————————
class Request(Base):
    __tablename__ = "request"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    ref: Mapped[str] = mapped_column(String, nullable=False, unique=True)  # REQ-2026-0417
    org_id: Mapped[str] = mapped_column(ForeignKey("organization.id"), nullable=False)

    type: Mapped[str] = mapped_column(String, default="NDA")
    direction: Mapped[Direction] = mapped_column(Enum(Direction), default=Direction.OUTBOUND)
    nda_type: Mapped[NdaType] = mapped_column(Enum(NdaType), default=NdaType.MUTUAL)
    our_role: Mapped[OurRole] = mapped_column(Enum(OurRole), default=OurRole.BOTH)

    state: Mapped[RequestState] = mapped_column(Enum(RequestState), default=RequestState.NEW)
    lane: Mapped[Lane | None] = mapped_column(Enum(Lane), nullable=True)

    requester_id: Mapped[str] = mapped_column(ForeignKey("person.id"), nullable=False)
    counterparty_id: Mapped[str] = mapped_column(ForeignKey("counterparty.id"), nullable=False)

    purpose: Mapped[str] = mapped_column(String, nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String, default="US")
    term_months: Mapped[int] = mapped_column(Integer, default=24)
    channel: Mapped[str] = mapped_column(String, default="FORM")  # FORM | SLACK | EMAIL | CHAT
    triage_reasons: Mapped[list] = mapped_column(JSON, default=list)

    document_id: Mapped[str | None] = mapped_column(ForeignKey("document.id"), nullable=True)

    # e-signature envelope tracking (populated on send)
    esign_envelope_id: Mapped[str | None] = mapped_column(String, nullable=True)
    esign_provider: Mapped[str | None] = mapped_column(String, nullable=True)  # stub | docusign
    esign_status: Mapped[str | None] = mapped_column(String, nullable=True)    # sent | completed | declined

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# ————————————————————— structured document model —————————————————————
class Document(Base):
    __tablename__ = "document"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organization.id"), nullable=False)
    request_id: Mapped[str] = mapped_column(String, nullable=False)
    origin: Mapped[str] = mapped_column(String, default="GENERATED")  # GENERATED | UPLOADED
    title: Mapped[str] = mapped_column(String, nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DocumentVersion(Base):
    __tablename__ = "document_version"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)  # provenance
    generated_by: Mapped[str] = mapped_column(String, default="playbook-assembly")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Clause(Base):
    """The addressable unit. In the outbound path each assembled clause is stored
    so the inbound redline engine (next slice) has spans to anchor edits to."""
    __tablename__ = "clause"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_version.id"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    section_no: Mapped[str] = mapped_column(String, default="")
    clause_type: Mapped[str | None] = mapped_column(String, nullable=True)
    heading: Mapped[str] = mapped_column(String, default="")
    body_text: Mapped[str] = mapped_column(Text, default="")
    source_rule_key: Mapped[str | None] = mapped_column(String, nullable=True)  # which playbook rule produced it


# ————————————————————————— approval ladder —————————————————————————
class ApprovalLadder(Base):
    __tablename__ = "approval_ladder"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    request_id: Mapped[str] = mapped_column(ForeignKey("request.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, default="PENDING")  # PENDING | APPROVED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    steps: Mapped[list[ApprovalStep]] = relationship(
        back_populates="ladder", order_by="ApprovalStep.ordinal"
    )


class ApprovalStep(Base):
    __tablename__ = "approval_step"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    ladder_id: Mapped[str] = mapped_column(ForeignKey("approval_ladder.id"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    rung: Mapped[str] = mapped_column(String, nullable=False)  # gc | vp_legal | requesting_manager
    assignee_user_id: Mapped[str | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    reason: Mapped[str] = mapped_column(String, default="")
    status: Mapped[StepStatus] = mapped_column(Enum(StepStatus), default=StepStatus.PENDING)
    decided_by: Mapped[str | None] = mapped_column(String, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ladder: Mapped[ApprovalLadder] = relationship(back_populates="steps")


# ——————————————— inbound review: engine output + governance gate ———————————————
class ReviewRun(Base):
    """One run of the hybrid engine over a counterparty document."""
    __tablename__ = "review_run"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    request_id: Mapped[str] = mapped_column(ForeignKey("request.id"), nullable=False)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_version.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, default="COMPLETE")  # COMPLETE | ABSTAINED
    summary: Mapped[dict] = mapped_column(JSON, default=dict)  # {compliant, fallback, deviation, missing, novel}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    changes: Mapped[list[ProposedChange]] = relationship(
        back_populates="run", order_by="ProposedChange.ordinal"
    )


class ProposedChange(Base):
    """A single engine finding + proposed redline. This IS the AgentDecision:
    nothing mutates the document until a human approves it."""
    __tablename__ = "proposed_change"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("review_run.id"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    clause_id: Mapped[str | None] = mapped_column(ForeignKey("clause.id"), nullable=True)  # null when MISSING
    section_no: Mapped[str] = mapped_column(String, default="")
    heading: Mapped[str] = mapped_column(String, default="")
    finding: Mapped[str] = mapped_column(String, nullable=False)  # DEVIATION | MISSING | NOVEL | ACCEPTABLE_FALLBACK
    rule_key: Mapped[str | None] = mapped_column(String, nullable=True)  # citation target
    before_text: Mapped[str] = mapped_column(Text, default="")
    after_text: Mapped[str] = mapped_column(Text, default="")  # proposed replacement / insertion
    rationale: Mapped[str] = mapped_column(Text, default="")
    checks: Mapped[list] = mapped_column(JSON, default=list)  # [{kind, name, passed, detail}]
    confidence: Mapped[float | None] = mapped_column(default=None)
    triggered_rung: Mapped[str] = mapped_column(String, default="none")
    decision: Mapped[str] = mapped_column(String, default="PENDING")  # PENDING | APPROVED | APPROVED_WITH_EDIT | REJECTED
    decided_by: Mapped[str | None] = mapped_column(String, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run: Mapped[ReviewRun] = relationship(back_populates="changes")


# ——————————————————— append-only, hash-chained audit ———————————————————
class AuditEvent(Base):
    """Tamper-evident ledger. ``content_hash`` = sha256 over the canonical row
    content INCLUDING ``prev_hash`` + ``chain_position``, so any post-hoc edit
    breaks the chain from that point forward. Never UPDATE or DELETE a row."""
    __tablename__ = "audit_event"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organization.id"), nullable=False)
    chain_position: Mapped[int] = mapped_column(Integer, nullable=False)
    prev_hash: Mapped[str] = mapped_column(String, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)

    actor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    actor_type: Mapped[ActorType] = mapped_column(Enum(ActorType), default=ActorType.SYSTEM)
    actor_label: Mapped[str] = mapped_column(String, default="System")
    action: Mapped[str] = mapped_column(String, nullable=False)  # request.created, change.approved, ...
    resource_type: Mapped[str] = mapped_column(String, nullable=False)
    resource_id: Mapped[str] = mapped_column(String, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

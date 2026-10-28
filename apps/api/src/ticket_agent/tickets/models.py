from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ticket_agent.shared.db import Base
from ticket_agent.tickets.domain import TicketStatus, WorkflowState


def utc_now() -> datetime:
    return datetime.now(UTC)


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        UniqueConstraint("source_system", "source_ticket_id", name="uq_ticket_source"),
        UniqueConstraint("idempotency_key", name="uq_ticket_idempotency_key"),
        Index("ix_tickets_state", "workflow_state", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    employee_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("digital_employees.id", ondelete="RESTRICT"),
        index=True,
    )
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    source_ticket_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_channel: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requester_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    customer_tier: Mapped[str] = mapped_column(String(32), default="standard", nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default=TicketStatus.OPEN, nullable=False)
    workflow_state: Mapped[str] = mapped_column(
        String(32), default=WorkflowState.RECEIVED, nullable=False
    )
    category_primary: Mapped[str | None] = mapped_column(String(64))
    category_secondary: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float | None] = mapped_column(Float)
    priority: Mapped[str | None] = mapped_column(String(8))
    risk_level: Mapped[str | None] = mapped_column(String(8))
    queue_id: Mapped[str | None] = mapped_column(String(64))
    needs_human: Mapped[bool] = mapped_column(default=False, nullable=False)
    human_reason: Mapped[str | None] = mapped_column(String(64))
    sync_status: Mapped[str] = mapped_column(String(24), default="NOT_STARTED", nullable=False)
    sync_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sync_error: Mapped[str | None] = mapped_column(Text)
    external_request_id: Mapped[str | None] = mapped_column(String(128))
    external_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class TicketAnalysis(Base):
    __tablename__ = "ticket_analyses"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    ticket_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ticket_version: Mapped[int] = mapped_column(Integer, nullable=False)
    classifier_name: Mapped[str] = mapped_column(String(64), nullable=False)
    category_primary: Mapped[str] = mapped_column(String(64), nullable=False)
    category_secondary: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(8), nullable=False)
    priority: Mapped[str] = mapped_column(String(8), nullable=False)
    queue_id: Mapped[str] = mapped_column(String(64), nullable=False)
    needs_human: Mapped[bool] = mapped_column(nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class AnswerDraft(Base):
    __tablename__ = "answer_drafts"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    ticket_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="NEEDS_REVIEW", nullable=False)
    citations_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    claims_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, default=list)
    generator_provider: Mapped[str | None] = mapped_column(String(64))
    generator_model: Mapped[str | None] = mapped_column(String(160))
    grounding_status: Mapped[str] = mapped_column(
        String(32), default="NO_KNOWLEDGE", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnswerQualityEvaluation(Base):
    """Human spot-check verdict for one adopted answer draft.

    One evaluation per draft: a re-check updates the verdict in place so the
    sampling queue never shows the same answer twice. Drafts, not tickets,
    are the unit because a ticket can regenerate answers after rejection.
    """

    __tablename__ = "answer_quality_evaluations"
    __table_args__ = (
        UniqueConstraint("draft_id", name="uq_answer_quality_evaluations_draft"),
        Index(
            "ix_answer_quality_evaluations_unit_created",
            "business_unit_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    draft_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("answer_drafts.id", ondelete="CASCADE"),
        nullable=False,
    )
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    hallucinated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    evaluator_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class WorkflowTransition(Base):
    __tablename__ = "workflow_transitions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    ticket_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_state: Mapped[str] = mapped_column(String(32), nullable=False)
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_ticket_time", "resource_id", "occurred_at"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    on_behalf_of: Mapped[str | None] = mapped_column(String(128))
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64))
    redacted_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


"""Durable workflow runs and leased steps.

A run is the retry/dead-letter unit: the outbox hands work off once, the
executor claims steps with a lease, and a worker that dies is recovered by
the beat task instead of by a human.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    DateTime,
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


def utc_now() -> datetime:
    return datetime.now(UTC)


class WorkflowRun(Base):
    """One recoverable execution of a business workflow.

    ``business_unit_id`` is mandatory: worker paths use ``system_session()``
    while HTTP readers stay tenant-scoped, so every query filters explicitly.
    """

    __tablename__ = "workflow_runs"
    __table_args__ = (
        UniqueConstraint(
            "business_unit_id",
            "workflow_type",
            "idempotency_key",
            name="uq_workflow_run_idempotency",
        ),
        Index(
            "ix_workflow_runs_unit_status_created",
            "business_unit_id",
            "status",
            "created_at",
        ),
        Index("ix_workflow_runs_aggregate_id", "aggregate_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    workflow_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False)
    current_step: Mapped[str | None] = mapped_column(String(64))
    context_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class WorkflowStep(Base):
    """One executable unit inside a run.

    ``lease_expires_at`` is the crash-recovery contract: a step claimed by a
    worker that died is put back to ``PENDING`` once the lease expires, and
    the attempt that was in flight is not counted as a failure.
    """

    __tablename__ = "workflow_steps"
    __table_args__ = (
        UniqueConstraint("workflow_run_id", "name", name="uq_workflow_step_name"),
        Index(
            "ix_workflow_steps_unit_status_available",
            "business_unit_id",
            "status",
            "available_at",
        ),
        Index("ix_workflow_steps_run_created", "workflow_run_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    workflow_run_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("workflow_runs.id", ondelete="CASCADE", name="fk_workflow_steps_run"),
        nullable=False,
    )
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

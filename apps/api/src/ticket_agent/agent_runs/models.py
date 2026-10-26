from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from ticket_agent.shared.db import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_unit_time", "business_unit_id", "started_at"),
        Index("ix_agent_runs_employee_time", "employee_id", "started_at"),
        Index("ix_agent_runs_ticket_time", "ticket_id", "started_at"),
        Index("ix_agent_runs_status_time", "status", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    employee_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("digital_employees.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ticket_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("tickets.id", ondelete="SET NULL"),
    )
    run_type: Mapped[str] = mapped_column(String(32), nullable=False)
    workflow_key: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    correlation_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )
    input_summary: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    result_summary: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

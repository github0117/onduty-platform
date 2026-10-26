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


class WorkforceTask(Base):
    __tablename__ = "workforce_tasks"
    __table_args__ = (
        Index(
            "ix_workforce_tasks_unit_status",
            "business_unit_id",
            "status",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    context_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    supervisor_employee_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("digital_employees.id", ondelete="SET NULL"),
    )
    status: Mapped[str] = mapped_column(
        String(24),
        default="PLAN_READY",
        nullable=False,
    )
    result_summary: Mapped[str | None] = mapped_column(Text)
    capability_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    capability_assessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class WorkforceTaskStep(Base):
    __tablename__ = "workforce_task_steps"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "sequence",
            name="uq_workforce_task_step_sequence",
        ),
        Index(
            "ix_workforce_task_steps_employee_status",
            "assigned_employee_id",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("workforce_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_employee_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("digital_employees.id", ondelete="RESTRICT"),
        nullable=False,
    )
    assigned_employee_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    route_decision_id: Mapped[UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(
        String(24),
        default="PENDING",
        nullable=False,
    )
    output_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

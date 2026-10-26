from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
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


class BusinessServiceEntry(Base):
    __tablename__ = "business_service_entries"
    __table_args__ = (
        UniqueConstraint(
            "business_unit_id",
            "code",
            name="uq_business_service_entry_unit_code",
        ),
        Index(
            "ix_business_service_entries_unit_status",
            "business_unit_id",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        default="ACTIVE",
        nullable=False,
    )
    default_employee_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("digital_employees.id", ondelete="SET NULL"),
    )
    fallback_employee_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("digital_employees.id", ondelete="SET NULL"),
    )
    human_queue_id: Mapped[str] = mapped_column(
        String(64),
        default="MANUAL_TRIAGE",
        nullable=False,
    )
    knowledge_scope_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    sla_policy_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
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


class BusinessServiceEntryEmployee(Base):
    __tablename__ = "business_service_entry_employees"
    __table_args__ = (
        UniqueConstraint(
            "service_entry_id",
            "employee_id",
            name="uq_business_service_entry_employee",
        ),
        Index(
            "ix_business_entry_employees_entry_enabled",
            "service_entry_id",
            "enabled",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    service_entry_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("business_service_entries.id", ondelete="CASCADE"),
        nullable=False,
    )
    employee_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("digital_employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    role_type: Mapped[str] = mapped_column(
        String(24),
        default="SPECIALIST",
        nullable=False,
    )
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

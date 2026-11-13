from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ticket_agent.shared.db import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class EfficiencyAssumption(Base):
    """Per business unit labor assumptions used to price saved human effort.

    The row is optional: when absent the service falls back to settings
    defaults. Once a ledger entry is written the values used are frozen in
    ``EfficiencyLedgerEntry.assumption_snapshot``.
    """

    __tablename__ = "efficiency_assumptions"
    __table_args__ = (
        UniqueConstraint(
            "business_unit_id",
            name="uq_efficiency_assumptions_unit",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="CNY", nullable=False)
    hourly_labor_cost: Mapped[float] = mapped_column(
        Numeric(12, 4), nullable=False
    )
    minutes_per_ticket: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    minutes_per_conversation: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False
    )
    minutes_per_listing: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class EfficiencyLedgerEntry(Base):
    """Append-only record of one unit of human effort saved by a digital employee."""

    __tablename__ = "efficiency_ledger_entries"
    __table_args__ = (
        UniqueConstraint(
            "business_unit_id",
            "source_type",
            "source_id",
            name="uq_efficiency_ledger_source",
        ),
        Index(
            "ix_efficiency_ledger_unit_occurred",
            "business_unit_id",
            "occurred_at",
        ),
        Index(
            "ix_efficiency_ledger_unit_employee",
            "business_unit_id",
            "employee_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    employee_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "digital_employees.id",
            ondelete="SET NULL",
            name="fk_efficiency_ledger_employee",
        ),
    )
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    human_minutes_saved: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    labor_cost_saved: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="CNY", nullable=False)
    assumption_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

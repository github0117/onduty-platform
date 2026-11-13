from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ticket_agent.shared.db import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class AgentSchedulingPolicy(Base):
    __tablename__ = "agent_scheduling_policies"

    business_unit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    enforce_published_schedule: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    updated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class AgentShiftTemplate(Base):
    __tablename__ = "agent_shift_templates"
    __table_args__ = (
        UniqueConstraint(
            "business_unit_id",
            "name",
            name="uq_agent_shift_templates_unit_name",
        ),
        Index(
            "ix_agent_shift_templates_unit_status",
            "business_unit_id",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    start_local: Mapped[time] = mapped_column(Time, nullable=False)
    end_local: Mapped[time] = mapped_column(Time, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class AgentRoster(Base):
    __tablename__ = "agent_rosters"
    __table_args__ = (
        Index(
            "ix_agent_rosters_unit_week",
            "business_unit_id",
            "week_start",
        ),
        Index(
            "uq_agent_rosters_unit_week_draft",
            "business_unit_id",
            "week_start",
            unique=True,
            postgresql_where=text("status = 'DRAFT'"),
            sqlite_where=text("status = 'DRAFT'"),
        ),
        Index(
            "uq_agent_rosters_unit_week_published",
            "business_unit_id",
            "week_start",
            unique=True,
            postgresql_where=text("status = 'PUBLISHED'"),
            sqlite_where=text("status = 'PUBLISHED'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="DRAFT", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    cloned_from_roster_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "agent_rosters.id",
            ondelete="SET NULL",
            name="fk_agent_rosters_cloned_from",
        ),
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    published_by: Mapped[str | None] = mapped_column(String(128))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class AgentRosterEntry(Base):
    __tablename__ = "agent_roster_entries"
    __table_args__ = (
        UniqueConstraint(
            "roster_id",
            "agent_id",
            "shift_date",
            name="uq_agent_roster_entries_agent_day",
        ),
        Index(
            "ix_agent_roster_entries_agent_window",
            "agent_id",
            "start_at",
            "end_at",
        ),
        Index(
            "ix_agent_roster_entries_roster_window",
            "roster_id",
            "start_at",
            "end_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    roster_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "agent_rosters.id",
            ondelete="CASCADE",
            name="fk_agent_roster_entries_roster",
        ),
        nullable=False,
    )
    shift_template_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "agent_shift_templates.id",
            ondelete="SET NULL",
            name="fk_agent_roster_entries_shift",
        ),
    )
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    agent_display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    shift_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    shift_name: Mapped[str] = mapped_column(String(100), nullable=False)
    shift_version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )

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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ticket_agent.shared.db import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class McpConnector(Base):
    __tablename__ = "mcp_connectors"
    __table_args__ = (
        UniqueConstraint(
            "business_unit_id",
            "code",
            name="uq_mcp_connector_business_code",
        ),
        Index("ix_mcp_connectors_unit_status", "business_unit_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    transport: Mapped[str] = mapped_column(
        String(32),
        default="streamable_http",
        nullable=False,
    )
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    header_env_json: Mapped[dict[str, str]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    timeout_seconds: Mapped[float] = mapped_column(
        Float,
        default=30.0,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default="ACTIVE",
        nullable=False,
    )
    tools_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    last_check_error: Mapped[str | None] = mapped_column(Text)
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


class DigitalEmployeeMcpBinding(Base):
    __tablename__ = "digital_employee_mcp_bindings"
    __table_args__ = (
        UniqueConstraint(
            "employee_id",
            "connector_id",
            name="uq_employee_mcp_connector",
        ),
        Index(
            "ix_employee_mcp_enabled",
            "employee_id",
            "enabled",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    employee_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("digital_employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    connector_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("mcp_connectors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allowed_tools_json: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    write_approved: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )


class McpToolApproval(Base):
    __tablename__ = "mcp_tool_approvals"
    __table_args__ = (
        Index(
            "ix_mcp_approval_unit_status_time",
            "business_unit_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_mcp_approval_ticket_status",
            "ticket_id",
            "status",
        ),
        Index(
            "ux_mcp_approval_active_fingerprint",
            "request_fingerprint",
            unique=True,
            postgresql_where=text(
                "status IN ('PENDING', 'EXECUTING', 'SUCCEEDED', 'FAILED')"
            ),
            sqlite_where=text(
                "status IN ('PENDING', 'EXECUTING', 'SUCCEEDED', 'FAILED')"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    employee_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    connector_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    ticket_id: Mapped[UUID | None] = mapped_column(Uuid)
    conversation_id: Mapped[UUID | None] = mapped_column(Uuid)
    tool_id: Mapped[str] = mapped_column(String(200), nullable=False)
    connector_code: Mapped[str] = mapped_column(String(100), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(200), nullable=False)
    arguments_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    execution_arguments_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    required_role: Mapped[str] = mapped_column(
        String(20),
        default="supervisor",
        nullable=False,
    )
    policy_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    request_fingerprint: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default="PENDING",
        nullable=False,
    )
    requested_by: Mapped[str] = mapped_column(String(128), nullable=False)
    request_correlation_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    request_tool_call_id: Mapped[UUID | None] = mapped_column(Uuid)
    execution_tool_call_id: Mapped[UUID | None] = mapped_column(Uuid)
    decided_by: Mapped[str | None] = mapped_column(String(128))
    decision_note: Mapped[str | None] = mapped_column(Text)
    execution_correlation_id: Mapped[str | None] = mapped_column(String(64))
    result_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    execution_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
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


class McpActionIncident(Base):
    __tablename__ = "mcp_action_incidents"
    __table_args__ = (
        UniqueConstraint(
            "approval_id",
            name="uq_mcp_incident_approval",
        ),
        Index(
            "ix_mcp_incident_unit_status_time",
            "business_unit_id",
            "status",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    approval_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    employee_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    ticket_id: Mapped[UUID | None] = mapped_column(Uuid)
    conversation_id: Mapped[UUID | None] = mapped_column(Uuid)
    tool_id: Mapped[str] = mapped_column(String(200), nullable=False)
    failure_class: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        default="OPEN",
        nullable=False,
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    required_action: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_to: Mapped[str | None] = mapped_column(String(128))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolution_outcome: Mapped[str | None] = mapped_column(String(32))
    reconciliation_status: Mapped[str] = mapped_column(
        String(24),
        default="NOT_REQUESTED",
        nullable=False,
    )
    reconciliation_tool_id: Mapped[str | None] = mapped_column(String(200))
    reconciliation_arguments_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    reconciliation_result_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    reconciliation_tool_call_id: Mapped[UUID | None] = mapped_column(Uuid)
    reconciliation_attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    last_reconciled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    compensation_tool_id: Mapped[str | None] = mapped_column(String(200))
    compensation_approval_id: Mapped[UUID | None] = mapped_column(Uuid)
    compensation_status: Mapped[str] = mapped_column(
        String(24),
        default="NOT_REQUESTED",
        nullable=False,
    )
    compensation_result_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
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

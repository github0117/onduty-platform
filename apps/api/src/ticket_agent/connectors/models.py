"""Generic external connectors.

A connector is one row per external system (email mailbox, read-only HTTP
JSON service).  Vendor differences live in ``config_json`` /
``field_mapping_json``; the runtime only knows the ``connector_type``.
"""

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


class ExternalConnector(Base):
    __tablename__ = "external_connectors"
    __table_args__ = (
        UniqueConstraint(
            "business_unit_id",
            "connector_key",
            name="uq_external_connector_business_key",
        ),
        Index(
            "ix_external_connectors_unit_status",
            "business_unit_id",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    connector_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    connector_type: Mapped[str] = mapped_column(String(24), nullable=False)
    direction: Mapped[str] = mapped_column(
        String(24),
        default="BIDIRECTIONAL",
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(24),
        default="ACTIVE",
        nullable=False,
    )
    config_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    field_mapping_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    # Environment variable name that holds the credential. The value itself
    # never enters the database, API responses or logs.
    secret_ref: Mapped[str | None] = mapped_column(String(200))
    auto_reply_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_health_status: Mapped[str | None] = mapped_column(String(24))
    last_health_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_health_error: Mapped[str | None] = mapped_column(Text)
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


class ExternalConnectorBinding(Base):
    __tablename__ = "external_connector_bindings"
    __table_args__ = (
        UniqueConstraint(
            "connector_id",
            "service_entry_id",
            name="uq_external_connector_entry",
        ),
        Index(
            "ix_external_connector_bindings_connector",
            "connector_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    connector_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("external_connectors.id", ondelete="CASCADE"),
        nullable=False,
    )
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    service_entry_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("business_service_entries.id", ondelete="SET NULL"),
    )
    employee_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("digital_employees.id", ondelete="SET NULL"),
    )
    allowed_operations_json: Mapped[list[str]] = mapped_column(
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


class ExternalInboundMessage(Base):
    __tablename__ = "external_inbound_messages"
    __table_args__ = (
        UniqueConstraint(
            "connector_id",
            "external_message_id",
            name="uq_external_inbound_message",
        ),
        Index(
            "ix_external_inbound_connector_created",
            "connector_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    connector_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("external_connectors.id", ondelete="CASCADE"),
        nullable=False,
    )
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    external_message_id: Mapped[str] = mapped_column(String(256), nullable=False)
    external_conversation_id: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
    )
    external_user_id: Mapped[str] = mapped_column(String(256), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    raw_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(24),
        default="RECEIVED",
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    conversation_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("customer_conversations.id", ondelete="SET NULL"),
    )
    ticket_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("tickets.id", ondelete="SET NULL"),
    )
    turn_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("conversation_turns.id", ondelete="SET NULL"),
    )
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )


class ExternalOutboundMessage(Base):
    __tablename__ = "external_outbound_messages"
    __table_args__ = (
        UniqueConstraint(
            "connector_id",
            "idempotency_key",
            name="uq_external_outbound_idempotency",
        ),
        Index(
            "ix_external_outbound_connector_created",
            "connector_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    connector_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("external_connectors.id", ondelete="CASCADE"),
        nullable=False,
    )
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    conversation_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("customer_conversations.id", ondelete="SET NULL"),
    )
    outbox_event_id: Mapped[UUID | None] = mapped_column(Uuid)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    recipient: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    external_message_id: Mapped[str | None] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(
        String(24),
        default="QUEUED",
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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

from datetime import UTC, datetime
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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ticket_agent.shared.db import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class CustomerConversation(Base):
    __tablename__ = "customer_conversations"
    __table_args__ = (
        Index("ix_customer_conversations_unit_status", "business_unit_id", "status"),
        UniqueConstraint(
            "external_connector_id",
            "external_thread_id",
            name="uq_customer_conversations_external_thread",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    service_entry_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("business_service_entries.id", ondelete="SET NULL"),
    )
    employee_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("digital_employees.id", ondelete="SET NULL")
    )
    # How the current employee was chosen: ROUTER (the entry router),
    # AUTO_HANDOFF (an automatic re-route) or MANUAL (a supervisor switch).
    # A manual switch also stamps ``employee_locked_at``; from then on the
    # router may not take the conversation back.
    employee_source: Mapped[str] = mapped_column(
        String(16), default="ROUTER", nullable=False
    )
    employee_locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    # Evidence for the "two consecutive turns asked for the same other
    # employee" rule. Reset whenever the router stops recommending a change.
    reroute_candidate_id: Mapped[UUID | None] = mapped_column(Uuid)
    reroute_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    auto_reroute_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    # Turn sequence of the last automatic re-route. Measured in turns (not
    # buyer messages) so the cooldown means "N conversation rounds".
    last_auto_reroute_turn_sequence: Mapped[int | None] = mapped_column(Integer)
    requester_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    category_name: Mapped[str | None] = mapped_column(String(120))
    category_profile_id: Mapped[UUID | None] = mapped_column(Uuid)
    channel: Mapped[str] = mapped_column(String(64), default="web_form", nullable=False)
    external_connector_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("external_connectors.id", ondelete="SET NULL"),
        index=True,
    )
    external_thread_id: Mapped[str | None] = mapped_column(String(256))
    external_subject: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", nullable=False)
    current_ticket_id: Mapped[UUID | None] = mapped_column(Uuid)
    assigned_agent_id: Mapped[str | None] = mapped_column(String(128))
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class CustomerMessage(Base):
    __tablename__ = "customer_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence", name="uq_customer_message_sequence"),
        Index("ix_customer_messages_conversation", "conversation_id", "sequence"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("customer_conversations.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    ticket_id: Mapped[UUID | None] = mapped_column(Uuid)
    # Which turn produced this message. A logical reference (no FK) in the same
    # style as ``ticket_id``: a database FK would make customer_messages and
    # conversation_turns reference each other.
    turn_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_conversation_turn_sequence",
        ),
        Index(
            "ix_conversation_turns_conversation_status",
            "conversation_id",
            "status",
        ),
        # A caller-supplied id makes resubmission of the same message a replay
        # instead of a second turn. Only rows that actually carry an id are
        # constrained, so old rows stay valid.
        Index(
            "uq_conversation_turns_client_message",
            "conversation_id",
            "client_message_id",
            unique=True,
            postgresql_where=text("client_message_id IS NOT NULL"),
            sqlite_where=text("client_message_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("customer_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    ticket_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("tickets.id", ondelete="SET NULL"),
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        default="PENDING",
        nullable=False,
    )
    correlation_id: Mapped[str | None] = mapped_column(String(128), index=True)
    client_message_id: Mapped[str | None] = mapped_column(String(128))
    # Snapshot of what the runtime actually put in front of the answer:
    # message sequences used, memory version, handoff id, budget, truncation.
    # NULL means no assembly was recorded (fast paths and pre-M1 turns).
    context_json: Mapped[dict[str, object] | None] = mapped_column(JSON)
    # The Skill contract this turn ran. ``skill_snapshot_json`` freezes the
    # definition (including its version), so editing the Skill later cannot
    # change what a finished turn is judged against.
    skill_code: Mapped[str | None] = mapped_column(String(128), index=True)
    skill_version: Mapped[int | None] = mapped_column(Integer)
    skill_snapshot_json: Mapped[dict[str, object] | None] = mapped_column(JSON)
    # Required steps / criteria and whether this turn satisfied them.
    completion_json: Mapped[dict[str, object] | None] = mapped_column(JSON)
    handoff_id: Mapped[UUID | None] = mapped_column(Uuid)
    # Optimistic concurrency guard for state transitions, mirroring the
    # customer_conversations/tickets pattern.
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    stage_label: Mapped[str] = mapped_column(
        String(200),
        default="已收到问题",
        nullable=False,
    )
    user_message_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("customer_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    assistant_message_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("customer_messages.id", ondelete="SET NULL"),
    )
    employee_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("digital_employees.id", ondelete="SET NULL"),
    )
    employee_config_revision: Mapped[int | None] = mapped_column(Integer)
    intent: Mapped[str | None] = mapped_column(String(64))
    analysis_json: Mapped[dict[str, object]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    response_provider: Mapped[str | None] = mapped_column(String(64))
    response_model: Mapped[str | None] = mapped_column(String(128))
    grounding_status: Mapped[str | None] = mapped_column(String(32))
    citations_json: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    trace_json: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    tool_calls_json: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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


class ConversationTurnEvent(Base):
    """Append-only log of what happened inside one conversation turn.

    The turn row keeps the latest state; this table keeps the order of
    transitions so an operator can answer "what did this turn actually do?"
    without re-deriving it from audit_events.
    """

    __tablename__ = "conversation_turn_events"
    __table_args__ = (
        UniqueConstraint(
            "turn_id",
            "sequence",
            name="uq_conversation_turn_event_sequence",
        ),
        Index(
            "ix_conversation_turn_events_conversation_created",
            "conversation_id",
            "created_at",
        ),
        Index(
            "ix_conversation_turn_events_turn_type",
            "turn_id",
            "event_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    turn_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("conversation_turns.id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("customer_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    stage_label: Mapped[str | None] = mapped_column(String(200))
    actor_type: Mapped[str] = mapped_column(
        String(24), default="SERVICE", nullable=False
    )
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(128))
    payload_json: Mapped[dict[str, object]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class ConversationMemory(Base):
    __tablename__ = "conversation_memories"

    conversation_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("customer_conversations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    summary: Mapped[str] = mapped_column(
        Text,
        default="",
        nullable=False,
    )
    slots_json: Mapped[dict[str, object]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    last_turn_sequence: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    # v1 rows stored bare ``{"repository": ..., "order_id": ...}``. The reader
    # upgrades them to the v2 shape, which tracks where each fact came from.
    schema_version: Mapped[int] = mapped_column(
        Integer,
        default=2,
        nullable=False,
        server_default="1",
    )
    summarized_through_sequence: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        server_default="0",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
        server_default="1",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class ConversationHandoff(Base):
    """A recorded transfer of one conversation from one employee to another.

    The handoff carries a deterministic summary of what the previous employee
    had established, so the next turn can start from facts instead of from a
    raw message window.
    """

    __tablename__ = "conversation_handoffs"
    __table_args__ = (
        # Retrying one transfer must not create a second record; handing the
        # same turn to a different employee is a separate transfer.
        UniqueConstraint(
            "from_turn_id",
            "to_employee_id",
            name="uq_conversation_handoff_from_turn_target",
        ),
        Index(
            "ix_conversation_handoffs_conversation_created",
            "conversation_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("customer_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    from_turn_id: Mapped[UUID | None] = mapped_column(Uuid)
    to_turn_id: Mapped[UUID | None] = mapped_column(Uuid)
    from_employee_id: Mapped[UUID | None] = mapped_column(Uuid)
    to_employee_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("digital_employees.id", ondelete="SET NULL"),
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    summary_json: Mapped[dict[str, object]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class AgentPresence(Base):
    __tablename__ = "agent_presence"
    __table_args__ = (
        UniqueConstraint("agent_id", name="uq_agent_presence_agent"),
        Index("ix_agent_presence_last_seen", "last_seen_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    business_unit_id: Mapped[str] = mapped_column(
        String(64),
        default="bu_demo",
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(24), default="ONLINE", nullable=False)
    actor_role: Mapped[str] = mapped_column(
        String(24),
        default="agent",
        nullable=False,
    )
    skills_json: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    risk_clearance: Mapped[str] = mapped_column(
        String(8),
        default="R2",
        nullable=False,
    )
    max_conversations: Mapped[int] = mapped_column(
        Integer,
        default=5,
        nullable=False,
    )
    auto_assign_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    current_conversation_id: Mapped[UUID | None] = mapped_column(Uuid)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class CustomerServiceNotification(Base):
    __tablename__ = "customer_service_notifications"
    __table_args__ = (
        Index(
            "ix_customer_service_notifications_status",
            "business_unit_id",
            "status",
        ),
        Index("ix_customer_service_notifications_conversation", "conversation_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("customer_conversations.id", ondelete="CASCADE"), nullable=False
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="OPEN", nullable=False)
    acknowledged_by: Mapped[str | None] = mapped_column(String(128))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

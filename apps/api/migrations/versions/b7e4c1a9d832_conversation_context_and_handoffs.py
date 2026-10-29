"""conversation context, message turn ids and employee handoffs

Revision ID: b7e4c1a9d832
Revises: f2a8d6c4b917
Create Date: 2026-10-29 10:20:00.000000

Runtime v2 M1 makes the context of a turn and the transfer between employees
first-class data:

* ``customer_messages.turn_id`` links each message to the turn that produced
  it, so an assistant message can be traced back to an employee and evidence.
* ``conversation_turns`` gains ``client_message_id`` (idempotent submission)
  and ``context_json`` (what the runtime actually assembled).
* ``conversation_memories`` gains ``schema_version`` / ``version`` /
  ``summarized_through_sequence`` so the v2 shape is written explicitly and
  the v1 rows can be upgraded lazily on read.
* ``conversation_handoffs`` records an employee switch together with the
  summary the next employee inherits.

Everything is additive: old rows get NULL or safe server defaults, and no
historical events are fabricated.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e4c1a9d832"
down_revision: str | None = "f2a8d6c4b917"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "customer_messages",
        sa.Column("turn_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_customer_messages_turn_id",
        "customer_messages",
        ["turn_id"],
    )

    op.add_column(
        "conversation_turns",
        sa.Column("client_message_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "conversation_turns",
        sa.Column("context_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "conversation_turns",
        sa.Column("handoff_id", sa.Uuid(), nullable=True),
    )
    # Partial unique index: only turns that actually carry a caller-supplied id
    # take part, so historical rows (all NULL) stay valid.
    op.create_index(
        "uq_conversation_turns_client_message",
        "conversation_turns",
        ["conversation_id", "client_message_id"],
        unique=True,
        postgresql_where=sa.text("client_message_id IS NOT NULL"),
        sqlite_where=sa.text("client_message_id IS NOT NULL"),
    )

    op.add_column(
        "conversation_memories",
        sa.Column(
            "schema_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "conversation_memories",
        sa.Column(
            "summarized_through_sequence",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "conversation_memories",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )

    op.create_table(
        "conversation_handoffs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("from_turn_id", sa.Uuid(), nullable=True),
        sa.Column("to_turn_id", sa.Uuid(), nullable=True),
        sa.Column("from_employee_id", sa.Uuid(), nullable=True),
        sa.Column("to_employee_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["customer_conversations.id"],
            name="fk_conversation_handoffs_conversation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["to_employee_id"],
            ["digital_employees.id"],
            name="fk_conversation_handoffs_to_employee",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        # Retrying the same transfer must not write a second record, but an
        # operator may hand the same turn to a different employee afterwards.
        sa.UniqueConstraint(
            "from_turn_id",
            "to_employee_id",
            name="uq_conversation_handoff_from_turn_target",
        ),
    )
    op.create_index(
        "ix_conversation_handoffs_conversation_created",
        "conversation_handoffs",
        ["conversation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_handoffs_conversation_created",
        table_name="conversation_handoffs",
    )
    op.drop_table("conversation_handoffs")
    op.drop_column("conversation_memories", "version")
    op.drop_column("conversation_memories", "summarized_through_sequence")
    op.drop_column("conversation_memories", "schema_version")
    op.drop_index(
        "uq_conversation_turns_client_message",
        table_name="conversation_turns",
    )
    op.drop_column("conversation_turns", "handoff_id")
    op.drop_column("conversation_turns", "context_json")
    op.drop_column("conversation_turns", "client_message_id")
    op.drop_index(
        "ix_customer_messages_turn_id",
        table_name="customer_messages",
    )
    op.drop_column("customer_messages", "turn_id")

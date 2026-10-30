"""conversation turn state machine and event log

Revision ID: f2a8d6c4b917
Revises: a9d3c7e5b214
Create Date: 2026-10-28 21:30:00.000000

Turns become the runtime transaction unit:

* ``conversation_turns`` gains a correlation id, an optimistic-concurrency
  ``version``, an attempt counter and a worker lease.
* ``conversation_turn_events`` records every state transition in order.

Existing rows keep working: the legacy vocabulary is rewritten in place
(``RECEIVED`` -> ``PENDING``, ``FAILED`` -> ``FAILED_RETRYABLE``) and the new
columns get safe server defaults. The migration is additive otherwise.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2a8d6c4b917"
down_revision: str | None = "a9d3c7e5b214"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_turn_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("turn_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage_label", sa.String(length=200), nullable=True),
        sa.Column("actor_type", sa.String(length=24), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["turn_id"],
            ["conversation_turns.id"],
            name="fk_conversation_turn_events_turn",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["customer_conversations.id"],
            name="fk_conversation_turn_events_conversation",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "turn_id",
            "sequence",
            name="uq_conversation_turn_event_sequence",
        ),
    )
    op.create_index(
        "ix_conversation_turn_events_conversation_created",
        "conversation_turn_events",
        ["conversation_id", "created_at"],
    )
    op.create_index(
        "ix_conversation_turn_events_turn_type",
        "conversation_turn_events",
        ["turn_id", "event_type"],
    )

    op.add_column(
        "conversation_turns",
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "conversation_turns",
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "conversation_turns",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "conversation_turns",
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_conversation_turns_correlation_id",
        "conversation_turns",
        ["correlation_id"],
    )
    op.create_index(
        "ix_conversation_turns_lease_expires_at",
        "conversation_turns",
        ["lease_expires_at"],
    )

    # Backfill the legacy vocabulary in place so the state machine can parse
    # every historical row.
    op.execute(
        "UPDATE conversation_turns SET status = 'PENDING' "
        "WHERE status = 'RECEIVED'"
    )
    op.execute(
        "UPDATE conversation_turns SET status = 'FAILED_RETRYABLE' "
        "WHERE status = 'FAILED'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE conversation_turns SET status = 'RECEIVED' "
        "WHERE status = 'PENDING'"
    )
    op.execute(
        "UPDATE conversation_turns SET status = 'FAILED' "
        "WHERE status IN ('FAILED_RETRYABLE', 'FAILED_TERMINAL')"
    )
    op.drop_index(
        "ix_conversation_turns_lease_expires_at",
        table_name="conversation_turns",
    )
    op.drop_index(
        "ix_conversation_turns_correlation_id",
        table_name="conversation_turns",
    )
    op.drop_column("conversation_turns", "lease_expires_at")
    op.drop_column("conversation_turns", "attempt_count")
    op.drop_column("conversation_turns", "version")
    op.drop_column("conversation_turns", "correlation_id")
    op.drop_index(
        "ix_conversation_turn_events_turn_type",
        table_name="conversation_turn_events",
    )
    op.drop_index(
        "ix_conversation_turn_events_conversation_created",
        table_name="conversation_turn_events",
    )
    op.drop_table("conversation_turn_events")

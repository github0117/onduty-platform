"""add conversation turns and memory

Revision ID: b8e3f1a7c642
Revises: e4b8c2d6f135
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8e3f1a7c642"
down_revision: str | None = "e4b8c2d6f135"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_turns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage_label", sa.String(length=200), nullable=False),
        sa.Column("user_message_id", sa.Uuid(), nullable=False),
        sa.Column("assistant_message_id", sa.Uuid(), nullable=True),
        sa.Column("employee_id", sa.Uuid(), nullable=True),
        sa.Column("employee_config_revision", sa.Integer(), nullable=True),
        sa.Column("intent", sa.String(length=64), nullable=True),
        sa.Column("analysis_json", sa.JSON(), nullable=False),
        sa.Column("response_provider", sa.String(length=64), nullable=True),
        sa.Column("response_model", sa.String(length=128), nullable=True),
        sa.Column("grounding_status", sa.String(length=32), nullable=True),
        sa.Column("citations_json", sa.JSON(), nullable=False),
        sa.Column("trace_json", sa.JSON(), nullable=False),
        sa.Column("tool_calls_json", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["assistant_message_id"],
            ["customer_messages.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["customer_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["digital_employees.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_message_id"],
            ["customer_messages.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_conversation_turn_sequence",
        ),
    )
    op.create_index(
        "ix_conversation_turns_conversation_status",
        "conversation_turns",
        ["conversation_id", "status"],
    )
    op.create_table(
        "conversation_memories",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("slots_json", sa.JSON(), nullable=False),
        sa.Column("last_turn_sequence", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["customer_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("conversation_id"),
    )


def downgrade() -> None:
    op.drop_table("conversation_memories")
    op.drop_index(
        "ix_conversation_turns_conversation_status",
        table_name="conversation_turns",
    )
    op.drop_table("conversation_turns")

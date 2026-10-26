"""mcp incident reconciliation and compensation

Revision ID: a7d2e9c5f314
Revises: f5c1d8a4e726
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7d2e9c5f314"
down_revision: str | None = "f5c1d8a4e726"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_action_incidents",
        sa.Column("resolution_outcome", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "mcp_action_incidents",
        sa.Column(
            "reconciliation_status",
            sa.String(length=24),
            nullable=False,
            server_default="NOT_REQUESTED",
        ),
    )
    op.add_column(
        "mcp_action_incidents",
        sa.Column("reconciliation_tool_id", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "mcp_action_incidents",
        sa.Column(
            "reconciliation_arguments_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "mcp_action_incidents",
        sa.Column(
            "reconciliation_result_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "mcp_action_incidents",
        sa.Column("reconciliation_tool_call_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "mcp_action_incidents",
        sa.Column(
            "reconciliation_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "mcp_action_incidents",
        sa.Column("last_reconciled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "mcp_action_incidents",
        sa.Column("compensation_tool_id", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "mcp_action_incidents",
        sa.Column("compensation_approval_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "mcp_action_incidents",
        sa.Column(
            "compensation_status",
            sa.String(length=24),
            nullable=False,
            server_default="NOT_REQUESTED",
        ),
    )
    op.add_column(
        "mcp_action_incidents",
        sa.Column(
            "compensation_result_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    for column in (
        "compensation_result_json",
        "compensation_status",
        "compensation_approval_id",
        "compensation_tool_id",
        "last_reconciled_at",
        "reconciliation_attempts",
        "reconciliation_tool_call_id",
        "reconciliation_result_json",
        "reconciliation_arguments_json",
        "reconciliation_tool_id",
        "reconciliation_status",
        "resolution_outcome",
    ):
        op.drop_column("mcp_action_incidents", column)

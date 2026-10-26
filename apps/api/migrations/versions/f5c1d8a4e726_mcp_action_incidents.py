"""mcp action incidents

Revision ID: f5c1d8a4e726
Revises: e8b4c2d7a615
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f5c1d8a4e726"
down_revision: str | None = "e8b4c2d7a615"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_action_incidents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("tool_id", sa.String(length=200), nullable=False),
        sa.Column("failure_class", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("required_action", sa.Text(), nullable=False),
        sa.Column("assigned_to", sa.String(length=128), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "approval_id",
            name="uq_mcp_incident_approval",
        ),
    )
    op.create_index(
        "ix_mcp_action_incidents_business_unit_id",
        "mcp_action_incidents",
        ["business_unit_id"],
    )
    op.create_index(
        "ix_mcp_action_incidents_approval_id",
        "mcp_action_incidents",
        ["approval_id"],
    )
    op.create_index(
        "ix_mcp_incident_unit_status_time",
        "mcp_action_incidents",
        ["business_unit_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mcp_incident_unit_status_time",
        table_name="mcp_action_incidents",
    )
    op.drop_index(
        "ix_mcp_action_incidents_approval_id",
        table_name="mcp_action_incidents",
    )
    op.drop_index(
        "ix_mcp_action_incidents_business_unit_id",
        table_name="mcp_action_incidents",
    )
    op.drop_table("mcp_action_incidents")

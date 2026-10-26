"""mcp tool approvals

Revision ID: a4d8e2c6f913
Revises: f2c9d5a8e741
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4d8e2c6f913"
down_revision: str | None = "f2c9d5a8e741"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_tool_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("connector_id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("tool_id", sa.String(length=200), nullable=False),
        sa.Column("connector_code", sa.String(length=100), nullable=False),
        sa.Column("tool_name", sa.String(length=200), nullable=False),
        sa.Column("arguments_json", sa.JSON(), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("requested_by", sa.String(length=128), nullable=False),
        sa.Column("request_correlation_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("request_tool_call_id", sa.Uuid(), nullable=True),
        sa.Column("execution_tool_call_id", sa.Uuid(), nullable=True),
        sa.Column("decided_by", sa.String(length=128), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("execution_correlation_id", sa.String(length=64), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mcp_tool_approvals_business_unit_id",
        "mcp_tool_approvals",
        ["business_unit_id"],
    )
    op.create_index(
        "ix_mcp_tool_approvals_employee_id",
        "mcp_tool_approvals",
        ["employee_id"],
    )
    op.create_index(
        "ix_mcp_tool_approvals_connector_id",
        "mcp_tool_approvals",
        ["connector_id"],
    )
    op.create_index(
        "ix_mcp_approval_unit_status_time",
        "mcp_tool_approvals",
        ["business_unit_id", "status", "created_at"],
    )
    op.create_index(
        "ix_mcp_approval_ticket_status",
        "mcp_tool_approvals",
        ["ticket_id", "status"],
    )
    op.create_index(
        "ix_mcp_approval_fingerprint",
        "mcp_tool_approvals",
        ["request_fingerprint"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mcp_approval_fingerprint",
        table_name="mcp_tool_approvals",
    )
    op.drop_index(
        "ix_mcp_approval_ticket_status",
        table_name="mcp_tool_approvals",
    )
    op.drop_index(
        "ix_mcp_approval_unit_status_time",
        table_name="mcp_tool_approvals",
    )
    op.drop_index(
        "ix_mcp_tool_approvals_connector_id",
        table_name="mcp_tool_approvals",
    )
    op.drop_index(
        "ix_mcp_tool_approvals_employee_id",
        table_name="mcp_tool_approvals",
    )
    op.drop_index(
        "ix_mcp_tool_approvals_business_unit_id",
        table_name="mcp_tool_approvals",
    )
    op.drop_table("mcp_tool_approvals")

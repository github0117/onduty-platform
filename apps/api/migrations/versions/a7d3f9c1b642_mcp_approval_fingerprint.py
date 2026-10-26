"""mcp approval active fingerprint

Revision ID: a7d3f9c1b642
Revises: c2d7a9f4b613
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7d3f9c1b642"
down_revision: str | None = "c2d7a9f4b613"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIVE_STATUSES = "status IN ('PENDING', 'EXECUTING', 'SUCCEEDED', 'FAILED')"


def upgrade() -> None:
    op.drop_index(
        "ix_mcp_approval_fingerprint",
        table_name="mcp_tool_approvals",
    )
    op.create_index(
        "ux_mcp_approval_active_fingerprint",
        "mcp_tool_approvals",
        ["request_fingerprint"],
        unique=True,
        postgresql_where=sa.text(ACTIVE_STATUSES),
        sqlite_where=sa.text(ACTIVE_STATUSES),
    )


def downgrade() -> None:
    op.drop_index(
        "ux_mcp_approval_active_fingerprint",
        table_name="mcp_tool_approvals",
    )
    op.create_index(
        "ix_mcp_approval_fingerprint",
        "mcp_tool_approvals",
        ["request_fingerprint"],
    )

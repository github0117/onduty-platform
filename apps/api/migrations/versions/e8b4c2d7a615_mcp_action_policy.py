"""mcp action policy snapshot

Revision ID: e8b4c2d7a615
Revises: d1f7a3b9c524
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8b4c2d7a615"
down_revision: str | None = "d1f7a3b9c524"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_tool_approvals",
        sa.Column(
            "required_role",
            sa.String(length=20),
            nullable=False,
            server_default="supervisor",
        ),
    )
    op.add_column(
        "mcp_tool_approvals",
        sa.Column(
            "policy_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("mcp_tool_approvals", "policy_json")
    op.drop_column("mcp_tool_approvals", "required_role")

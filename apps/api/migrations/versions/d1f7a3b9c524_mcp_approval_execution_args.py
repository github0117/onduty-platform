"""store exact mcp approval execution arguments

Revision ID: d1f7a3b9c524
Revises: a4d8e2c6f913
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d1f7a3b9c524"
down_revision: str | None = "a4d8e2c6f913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_tool_approvals",
        sa.Column(
            "execution_arguments_json",
            sa.JSON(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("mcp_tool_approvals", "execution_arguments_json")

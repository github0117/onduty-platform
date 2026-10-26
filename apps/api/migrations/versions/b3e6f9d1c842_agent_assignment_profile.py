"""agent assignment profile

Revision ID: b3e6f9d1c842
Revises: a7d2e9c5f314
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3e6f9d1c842"
down_revision: str | None = "a7d2e9c5f314"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_presence",
        sa.Column(
            "business_unit_id",
            sa.String(length=64),
            nullable=False,
            server_default="bu_demo",
        ),
    )
    op.add_column(
        "agent_presence",
        sa.Column(
            "actor_role",
            sa.String(length=24),
            nullable=False,
            server_default="agent",
        ),
    )
    op.add_column(
        "agent_presence",
        sa.Column(
            "skills_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "agent_presence",
        sa.Column(
            "risk_clearance",
            sa.String(length=8),
            nullable=False,
            server_default="R2",
        ),
    )
    op.add_column(
        "agent_presence",
        sa.Column(
            "max_conversations",
            sa.Integer(),
            nullable=False,
            server_default="5",
        ),
    )
    op.add_column(
        "agent_presence",
        sa.Column(
            "auto_assign_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_presence", "auto_assign_enabled")
    op.drop_column("agent_presence", "max_conversations")
    op.drop_column("agent_presence", "risk_clearance")
    op.drop_column("agent_presence", "skills_json")
    op.drop_column("agent_presence", "actor_role")
    op.drop_column("agent_presence", "business_unit_id")

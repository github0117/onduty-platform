"""sticky conversation employee and reroute evidence

Revision ID: c4f1a7d29b63
Revises: b7e4c1a9d832
Create Date: 2026-10-29 15:10:00.000000

A conversation used to re-run the entry router on every buyer message, so the
employee could change mid-conversation on a single ambiguous message. The
employee is now the conversation's owner; a re-route needs evidence that
survives more than one message.

* ``employee_source`` says how the current employee was chosen.
* ``employee_locked_at`` marks a manual switch: the router may not override it.
* ``reroute_candidate_id`` / ``reroute_streak`` count consecutive turns that
  recommend the same other employee.
* ``auto_reroute_count`` / ``last_auto_reroute_turn_sequence`` bound how often
  a conversation may switch itself and how many turns apart the switches are.

All columns are additive with safe server defaults, so pre-migration rows keep
working: they read as ROUTER (not locked) with no reroute history.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4f1a7d29b63"
down_revision: str | None = "b7e4c1a9d832"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "customer_conversations",
        sa.Column(
            "employee_source",
            sa.String(length=16),
            nullable=False,
            server_default="ROUTER",
        ),
    )
    op.add_column(
        "customer_conversations",
        sa.Column("employee_locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "customer_conversations",
        sa.Column("reroute_candidate_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "customer_conversations",
        sa.Column(
            "reroute_streak",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "customer_conversations",
        sa.Column(
            "auto_reroute_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "customer_conversations",
        sa.Column(
            "last_auto_reroute_turn_sequence", sa.Integer(), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("customer_conversations", "last_auto_reroute_turn_sequence")
    op.drop_column("customer_conversations", "auto_reroute_count")
    op.drop_column("customer_conversations", "reroute_streak")
    op.drop_column("customer_conversations", "reroute_candidate_id")
    op.drop_column("customer_conversations", "employee_locked_at")
    op.drop_column("customer_conversations", "employee_source")

"""route evaluation dataset

Revision ID: e7a1c3d5b9f2
Revises: c7d4e1a9b352
Create Date: 2026-10-27 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "e7a1c3d5b9f2"
down_revision: str | None = "c7d4e1a9b352"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "digital_employee_route_evaluation_cases",
        sa.Column(
            "dataset",
            sa.String(length=16),
            server_default="TUNING",
            nullable=False,
        ),
    )
    op.add_column(
        "digital_employee_route_evaluation_runs",
        sa.Column(
            "dataset",
            sa.String(length=16),
            server_default="TUNING",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "digital_employee_route_evaluation_runs",
        "dataset",
    )
    op.drop_column(
        "digital_employee_route_evaluation_cases",
        "dataset",
    )

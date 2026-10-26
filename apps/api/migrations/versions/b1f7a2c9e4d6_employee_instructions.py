"""employee instruction prompt

Revision ID: b1f7a2c9e4d6
Revises: a7d3f9c1b642
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b1f7a2c9e4d6"
down_revision: str | None = "a7d3f9c1b642"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 员工当前配置和历史修订都保留提示词，便于审计某次回复实际使用了
    # 哪个版本的员工提示词。
    op.add_column(
        "digital_employees",
        sa.Column(
            "instruction_text",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "digital_employee_revisions",
        sa.Column(
            "instruction_text",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )


def downgrade() -> None:
    op.drop_column("digital_employee_revisions", "instruction_text")
    op.drop_column("digital_employees", "instruction_text")

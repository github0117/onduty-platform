"""tool allowlist for default employee

Revision ID: e55feed5e13b
Revises: ec399ae24b62
Create Date: 2026-10-23 13:14:01.230267
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'e55feed5e13b'
down_revision: str | None = 'ec399ae24b62'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""
    op.execute(
        """
        UPDATE digital_employees
        SET tool_allowlist_json =
            '["ticket.read","knowledge.search","draft.create","ticket.sync"]'
        WHERE employee_key = 'customer_service_ticket_v1'
        """
    )


def downgrade() -> None:
    """Revert the migration."""
    op.execute(
        """
        UPDATE digital_employees
        SET tool_allowlist_json = '["ticket.read","ticket.sync"]'
        WHERE employee_key = 'customer_service_ticket_v1'
        """
    )


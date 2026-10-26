"""deduplicate knowledge evaluation cases

Revision ID: c8f2a4d7e910
Revises: a5c9e2f7d831
Create Date: 2026-10-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c8f2a4d7e910"
down_revision: str | None = "a5c9e2f7d831"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    identity_partition = """
        PARTITION BY
            business_unit_id,
            COALESCE(knowledge_space_id::text, ''),
            COALESCE(employee_id::text, ''),
            md5(regexp_replace(lower(btrim(query)), '\\s+', ' ', 'g'))
    """
    ranked = f"""
        WITH ranked AS (
            SELECT
                id,
                first_value(id) OVER (
                    {identity_partition}
                    ORDER BY enabled DESC, created_at, id::text
                ) AS keeper_id
            FROM knowledge_evaluation_cases
        )
    """
    op.execute(
        ranked
        + """
        UPDATE knowledge_repair_tasks AS task
        SET evaluation_case_id = ranked.keeper_id
        FROM ranked
        WHERE task.evaluation_case_id = ranked.id
          AND ranked.id <> ranked.keeper_id
        """
    )
    op.execute(
        ranked
        + """
        DELETE FROM knowledge_evaluation_cases AS duplicate
        USING ranked
        WHERE duplicate.id = ranked.id
          AND ranked.id <> ranked.keeper_id
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_knowledge_evaluation_case_identity
        ON knowledge_evaluation_cases (
            business_unit_id,
            COALESCE(knowledge_space_id::text, ''),
            COALESCE(employee_id::text, ''),
            md5(regexp_replace(lower(btrim(query)), '\\s+', ' ', 'g'))
        )
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        "DROP INDEX IF EXISTS uq_knowledge_evaluation_case_identity"
    )

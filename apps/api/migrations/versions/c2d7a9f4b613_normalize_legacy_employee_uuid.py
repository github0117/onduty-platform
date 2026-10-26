"""normalize legacy employee UUID storage

Revision ID: c2d7a9f4b613
Revises: b8e3f1a7c642
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "c2d7a9f4b613"
down_revision: str | None = "b8e3f1a7c642"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_EMPLOYEE_ID = "00000000-0000-0000-0000-000000000101"
CANONICAL_EMPLOYEE_ID = "00000000000000000000000000000101"


def upgrade() -> None:
    _normalize_employee_id(LEGACY_EMPLOYEE_ID, CANONICAL_EMPLOYEE_ID)


def downgrade() -> None:
    _normalize_employee_id(CANONICAL_EMPLOYEE_ID, LEGACY_EMPLOYEE_ID)


def _normalize_employee_id(source: str, target: str) -> None:
    if context.is_offline_mode():
        return
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    inspector = sa.inspect(bind)
    if not inspector.has_table("digital_employees"):
        return
    parent_exists = bind.execute(
        sa.text(
            "SELECT 1 FROM digital_employees WHERE id = :employee_id"
        ),
        {"employee_id": source},
    ).scalar()
    if parent_exists is None:
        return
    bind.exec_driver_sql("PRAGMA defer_foreign_keys = ON")
    for table_name in inspector.get_table_names():
        for column in inspector.get_columns(table_name):
            column_name = str(column["name"])
            if (
                table_name == "digital_employees"
                and column_name == "id"
            ):
                continue
            if not column_name.endswith("employee_id"):
                continue
            quoted_table = _quote_identifier(table_name)
            quoted_column = _quote_identifier(column_name)
            bind.exec_driver_sql(
                f"UPDATE {quoted_table} SET {quoted_column} = ? "
                f"WHERE CAST({quoted_column} AS TEXT) = ?",
                (target, source),
            )
    bind.exec_driver_sql(
        "UPDATE digital_employees SET id = ? WHERE id = ?",
        (target, source),
    )
    violations = bind.exec_driver_sql(
        "PRAGMA foreign_key_check"
    ).fetchall()
    if violations:
        raise RuntimeError(
            "Employee UUID normalization left foreign key violations: "
            f"{violations[:5]}"
        )


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'

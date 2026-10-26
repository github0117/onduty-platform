"""backfill employee configuration revisions

Revision ID: d2e7b4c9a351
Revises: c9f4a1d8b263
Create Date: 2026-10-24
"""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "d2e7b4c9a351"
down_revision: str | None = "c9f4a1d8b263"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT e.id, e.config_revision, e.domain, e.template_code,
                   e.manifest_json, e.created_by, e.created_at
            FROM digital_employees e
            LEFT JOIN digital_employee_revisions r
              ON r.employee_id = e.id
            WHERE r.id IS NULL
            """
        )
    ).mappings()
    for row in rows:
        manifest = row["manifest_json"] or {}
        if isinstance(manifest, str):
            manifest = json.loads(manifest)
        manifest = {
            **manifest,
            "schema_version": manifest.get("schema_version", 1),
            "domain": manifest.get("domain", row["domain"]),
            "template_code": manifest.get(
                "template_code",
                row["template_code"],
            ),
        }
        connection.execute(
            sa.text(
                """
                INSERT INTO digital_employee_revisions (
                    id, employee_id, revision, status, manifest_json,
                    change_note, created_by, created_at, published_at
                ) VALUES (
                    :id, :employee_id, :revision, 'PUBLISHED',
                    CAST(:manifest_json AS JSON), :change_note,
                    :created_by, :created_at, :published_at
                )
                """
            ),
            {
                "id": str(uuid4()),
                "employee_id": str(row["id"]),
                "revision": row["config_revision"],
                "manifest_json": json.dumps(manifest, ensure_ascii=False),
                "change_note": "Backfilled existing employee manifest",
                "created_by": row["created_by"],
                "created_at": row["created_at"] or datetime.now(UTC),
                "published_at": row["created_at"] or datetime.now(UTC),
            },
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM digital_employee_revisions "
            "WHERE change_note = 'Backfilled existing employee manifest'"
        )
    )

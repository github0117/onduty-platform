import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def test_fresh_sqlite_migrations_normalize_employee_ids(
    tmp_path: Path,
) -> None:
    api_root = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "migrations.db"
    environment = {
        **os.environ,
        "APP_ENV": "test",
        "DATABASE_URL": f"sqlite:///{database_path}",
        "MODEL_PROVIDER": "local",
    }
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "head",
        ],
        cwd=api_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    with sqlite3.connect(database_path) as connection:
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()
        default_employee = connection.execute(
            "SELECT id FROM digital_employees "
            "WHERE employee_key = 'customer_service_ticket_v1'"
        ).fetchone()
        violations = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

    assert revision == ("c7d4e1a9b352",)
    assert default_employee == (
        "00000000000000000000000000000101",
    )
    assert violations == []

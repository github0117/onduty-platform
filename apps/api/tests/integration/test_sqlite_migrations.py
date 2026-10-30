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
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        default_employee = connection.execute(
            "SELECT id FROM digital_employees WHERE employee_key = 'customer_service_ticket_v1'"
        ).fetchone()
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()

    assert revision == ("e1a7c4d90b62",)
    assert default_employee == ("00000000000000000000000000000101",)
    assert violations == []


def test_evaluation_dataset_migration_backfills_legacy_cases_to_holdout(
    tmp_path: Path,
) -> None:
    api_root = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "legacy-migrations.db"
    environment = {
        **os.environ,
        "APP_ENV": "test",
        "DATABASE_URL": f"sqlite:///{database_path}",
        "MODEL_PROVIDER": "local",
    }

    def alembic(*arguments: str) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "alembic", *arguments],
            cwd=api_root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr

    alembic("upgrade", "d5e1f8c2b903")
    legacy_case_id = "a" * 32
    legacy_run_id = "b" * 32
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO knowledge_evaluation_cases ("
            "id, business_unit_id, name, query, expected_titles_json, "
            "expect_no_grounding, scope_json, enabled, created_by, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                legacy_case_id,
                "bu_demo",
                "旧版门禁案例",
                "旧版问题",
                '["旧版文档"]',
                0,
                "{}",
                1,
                "legacy",
                "2026-01-01 00:00:00.000000",
                "2026-01-01 00:00:00.000000",
            ),
        )
        connection.execute(
            "INSERT INTO knowledge_evaluation_runs ("
            "id, business_unit_id, status, verdict, top_k, case_count, "
            "passed_cases, failed_cases, thresholds_json, results_json, "
            "created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                legacy_run_id,
                "bu_demo",
                "SUCCEEDED",
                "PASS",
                5,
                1,
                1,
                0,
                "{}",
                "[]",
                "legacy",
                "2026-01-01 00:00:00.000000",
            ),
        )
        connection.commit()

    alembic("upgrade", "head")

    with sqlite3.connect(database_path) as connection:
        legacy_case = connection.execute(
            "SELECT dataset, expected_chunk_ids_json, "
            "expected_document_ids_json, negative_document_ids_json "
            "FROM knowledge_evaluation_cases WHERE id = ?",
            (legacy_case_id,),
        ).fetchone()
        legacy_run = connection.execute(
            "SELECT dataset, baseline_json FROM knowledge_evaluation_runs "
            "WHERE id = ?",
            (legacy_run_id,),
        ).fetchone()
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()

    assert revision == ("e1a7c4d90b62",)
    assert legacy_case == ("HOLDOUT", "[]", "[]", "[]")
    assert legacy_run == ("TUNING", None)

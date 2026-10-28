from __future__ import annotations

import importlib.util
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

API_ROOT = Path(__file__).parents[2]
SCRIPT = API_ROOT / "scripts" / "migration_preflight.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_preflight", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves the defining module through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run_script(database_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "APP_ENV": "test",
        "DATABASE_URL": f"sqlite:///{database_path}",
        "MODEL_PROVIDER": "local",
        "PYTHONPATH": str(API_ROOT / "src"),
    }
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=API_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _upgrade(database_path: Path, revision: str = "head") -> None:
    environment = {
        **os.environ,
        "APP_ENV": "test",
        "DATABASE_URL": f"sqlite:///{database_path}",
        "MODEL_PROVIDER": "local",
    }
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=API_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.fixture
def script() -> ModuleType:
    return _load_script()


def test_inspect_marks_database_at_head(script: ModuleType) -> None:
    state: Any = script.inspect_migration_state(
        "head1", ("head1",), ("head1", "older")
    )

    assert state.status == "at_head"


def test_inspect_marks_database_behind_head(script: ModuleType) -> None:
    state: Any = script.inspect_migration_state(
        "older", ("head1",), ("head1", "older")
    )

    assert state.status == "pending"


def test_inspect_marks_unshipped_revision(script: ModuleType) -> None:
    state: Any = script.inspect_migration_state(
        "not-in-image", ("head1",), ("head1", "older")
    )

    assert state.status == "unknown"


def test_inspect_marks_fresh_database(script: ModuleType) -> None:
    state: Any = script.inspect_migration_state(None, ("head1",), ("head1",))

    assert state.status == "empty"


def test_inspect_treats_diverged_or_missing_heads_as_config_error(
    script: ModuleType,
) -> None:
    diverged: Any = script.inspect_migration_state(
        "head1", ("head1", "head2"), ("head1", "head2")
    )
    missing: Any = script.inspect_migration_state(None, (), ())

    assert diverged.status == "multiple_heads"
    assert missing.status == "multiple_heads"


def test_cli_allows_fresh_database_only_with_allow_pending(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "fresh.db"

    blocked = _run_script(database_path, "--expect-head")
    allowed = _run_script(database_path, "--allow-pending")

    assert blocked.returncode == 3
    assert "migration_preflight=empty" in blocked.stdout
    assert allowed.returncode == 0
    assert "migration_preflight=empty" in allowed.stdout


def test_cli_confirms_head_after_upgrade(tmp_path: Path) -> None:
    database_path = tmp_path / "migrated.db"
    _upgrade(database_path)

    completed = _run_script(database_path, "--expect-head")

    assert completed.returncode == 0, completed.stderr
    assert "migration_preflight=at_head" in completed.stdout


def test_cli_refuses_revision_this_image_does_not_ship(tmp_path: Path) -> None:
    database_path = tmp_path / "ahead.db"
    _upgrade(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("UPDATE alembic_version SET version_num = 'deadbeef1234'")
        connection.commit()

    completed = _run_script(database_path, "--allow-pending")

    assert completed.returncode == 2
    assert "migration_preflight=unknown" in completed.stdout
    assert "does not ship" in completed.stderr

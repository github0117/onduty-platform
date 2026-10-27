import subprocess
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from ticket_agent import main as main_module

ADMIN_HEADERS = {
    "X-Actor-Id": "demo-admin",
    "X-Actor-Role": "admin",
    "X-Business-Unit-Id": "bu_demo",
}
CONFIRMATION_HEADERS = {
    **ADMIN_HEADERS,
    "X-Demo-Reset-Confirm": "reset-bu_demo",
}


@pytest.fixture(autouse=True)
def clear_demo_reset_jobs() -> Generator[None, None, None]:
    with main_module.demo_reset_jobs_lock:
        main_module.demo_reset_jobs.clear()
    yield
    with main_module.demo_reset_jobs_lock:
        main_module.demo_reset_jobs.clear()


def _job_status(
    client: TestClient,
    job_id: str,
    headers: dict[str, str] = ADMIN_HEADERS,
) -> dict[str, object]:
    response = client.get(f"/api/v1/demo/reset/{job_id}", headers=headers)
    assert response.status_code == 200
    return response.json()


def test_demo_reset_requires_admin(
    client: TestClient,
    monkeypatch,
) -> None:
    def unexpected_run(*args, **kwargs):
        raise AssertionError("seed script must not run for a non-admin actor")

    monkeypatch.setattr(main_module.subprocess, "run", unexpected_run)

    response = client.post(
        "/api/v1/demo/reset",
        json={},
        headers={
            "X-Actor-Id": "demo-agent",
            "X-Actor-Role": "agent",
            "X-Business-Unit-Id": "bu_demo",
            "X-Demo-Reset-Confirm": "reset-bu_demo",
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_demo_reset_rejects_non_admin_knowledge_roles(
    client: TestClient,
    monkeypatch,
) -> None:
    def unexpected_run(*args, **kwargs):
        raise AssertionError("seed script must not run for a knowledge operator")

    monkeypatch.setattr(main_module.subprocess, "run", unexpected_run)

    response = client.post(
        "/api/v1/demo/reset",
        json={},
        headers={
            "X-Actor-Id": "demo-knowledge",
            "X-Actor-Role": "knowledge_operator",
            "X-Business-Unit-Id": "bu_demo",
            "X-Demo-Reset-Confirm": "reset-bu_demo",
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_demo_reset_is_disabled_outside_demo_environment(
    client: TestClient,
    monkeypatch,
) -> None:
    def unexpected_run(*args, **kwargs):
        raise AssertionError("seed script must not run outside a demo environment")

    monkeypatch.setattr(main_module.settings, "app_env", "production")
    monkeypatch.setattr(main_module.subprocess, "run", unexpected_run)

    response = client.post(
        "/api/v1/demo/reset",
        json={},
        headers=CONFIRMATION_HEADERS,
    )

    assert response.status_code == 403
    assert response.json()["code"] == "DEMO_RESET_DISABLED"


def test_demo_reset_can_be_disabled_by_settings(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(main_module.settings, "demo_reset_enabled", False)

    response = client.post(
        "/api/v1/demo/reset",
        json={},
        headers=CONFIRMATION_HEADERS,
    )

    assert response.status_code == 403
    assert response.json()["code"] == "DEMO_RESET_DISABLED"


def test_demo_reset_requires_explicit_confirmation(
    client: TestClient,
    monkeypatch,
) -> None:
    def unexpected_run(*args, **kwargs):
        raise AssertionError("seed script must not run without confirmation")

    monkeypatch.setattr(main_module.subprocess, "run", unexpected_run)

    response = client.post(
        "/api/v1/demo/reset",
        json={},
        headers=ADMIN_HEADERS,
    )

    assert response.status_code == 403
    assert response.json()["code"] == "DEMO_RESET_CONFIRMATION_REQUIRED"


def test_demo_reset_is_scoped_to_the_demo_tenant(
    client: TestClient,
    monkeypatch,
) -> None:
    def unexpected_run(*args, **kwargs):
        raise AssertionError("seed script must not run for another tenant")

    monkeypatch.setattr(main_module.subprocess, "run", unexpected_run)

    response = client.post(
        "/api/v1/demo/reset",
        json={},
        headers={
            **CONFIRMATION_HEADERS,
            "X-Business-Unit-Id": "bu_acceptance",
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "DEMO_RESET_UNIT_UNSUPPORTED"


def test_demo_reset_runs_seed_script_in_background(
    client: TestClient,
    monkeypatch,
) -> None:
    observed: dict[str, object] = {}

    def successful_run(command, **kwargs):
        observed["command"] = command
        observed["timeout"] = kwargs["timeout"]
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr(main_module.subprocess, "run", successful_run)
    monkeypatch.setattr(
        main_module.settings,
        "demo_reset_base_url",
        "http://127.0.0.1:9911",
    )

    response = client.post(
        "/api/v1/demo/reset",
        json={},
        headers=CONFIRMATION_HEADERS,
    )

    assert response.status_code == 202
    started = response.json()
    assert started["status"] == "QUEUED"
    assert started["business_unit_id"] == "bu_demo"
    assert started["job_id"]

    command = observed["command"]
    assert isinstance(command, list)
    assert command[-1] == "http://127.0.0.1:9911"
    assert observed["timeout"] == 240

    status = _job_status(client, started["job_id"])
    assert status["status"] == "SUCCEEDED"
    assert status["code"] is None
    assert status["message"] == "演示数据已检查并恢复。"
    assert status["created_by"] == "demo-admin"
    assert status["finished_at"]


def test_demo_reset_reports_seed_failure(
    client: TestClient,
    monkeypatch,
) -> None:
    def failed_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="seed failed safely",
        )

    monkeypatch.setattr(main_module.subprocess, "run", failed_run)

    response = client.post(
        "/api/v1/demo/reset",
        json={},
        headers=CONFIRMATION_HEADERS,
    )

    assert response.status_code == 202
    status = _job_status(client, response.json()["job_id"])
    assert status["status"] == "FAILED"
    assert status["code"] == "DEMO_RESET_FAILED"


def test_demo_reset_reports_timeout_and_releases_lock(
    client: TestClient,
    monkeypatch,
) -> None:
    def timed_out_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(main_module.subprocess, "run", timed_out_run)

    response = client.post(
        "/api/v1/demo/reset",
        json={},
        headers=CONFIRMATION_HEADERS,
    )

    assert response.status_code == 202
    status = _job_status(client, response.json()["job_id"])
    assert status["status"] == "FAILED"
    assert status["code"] == "DEMO_RESET_TIMEOUT"
    assert main_module.demo_reset_lock.acquire(blocking=False)
    main_module.demo_reset_lock.release()


def test_demo_reset_rejects_a_job_that_is_already_running(
    client: TestClient,
    monkeypatch,
) -> None:
    def unexpected_run(*args, **kwargs):
        raise AssertionError("seed script must not run while another reset is active")

    monkeypatch.setattr(main_module.subprocess, "run", unexpected_run)
    with main_module.demo_reset_jobs_lock:
        main_module.demo_reset_jobs["running-job"] = {
            "job_id": "running-job",
            "business_unit_id": "bu_demo",
            "status": "RUNNING",
            "message": "正在检查并恢复演示数据。",
            "code": None,
            "created_by": "demo-admin",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "finished_at": None,
        }

    response = client.post(
        "/api/v1/demo/reset",
        json={},
        headers=CONFIRMATION_HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["code"] == "DEMO_RESET_IN_PROGRESS"


def test_demo_reset_status_is_tenant_scoped(
    client: TestClient,
    monkeypatch,
) -> None:
    def successful_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr(main_module.subprocess, "run", successful_run)

    response = client.post(
        "/api/v1/demo/reset",
        json={},
        headers=CONFIRMATION_HEADERS,
    )
    assert response.status_code == 202

    denied = client.get(
        f"/api/v1/demo/reset/{response.json()['job_id']}",
        headers={
            "X-Actor-Id": "demo-admin",
            "X-Actor-Role": "admin",
            "X-Business-Unit-Id": "bu_acceptance",
        },
    )

    assert denied.status_code == 403
    assert denied.json()["code"] == "BUSINESS_UNIT_ACCESS_DENIED"


def test_demo_reset_status_reports_unknown_jobs(client: TestClient) -> None:
    response = client.get("/api/v1/demo/reset/missing-job", headers=ADMIN_HEADERS)

    assert response.status_code == 404
    assert response.json()["code"] == "DEMO_RESET_JOB_NOT_FOUND"


def test_demo_reset_status_requires_admin(client: TestClient) -> None:
    response = client.get(
        "/api/v1/demo/reset/missing-job",
        headers={
            "X-Actor-Id": "demo-knowledge",
            "X-Actor-Role": "knowledge_operator",
            "X-Business-Unit-Id": "bu_demo",
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"

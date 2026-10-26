import subprocess

from fastapi.testclient import TestClient

from ticket_agent import main as main_module

ADMIN_HEADERS = {
    "X-Actor-Id": "demo-admin",
    "X-Actor-Role": "admin",
    "X-Business-Unit-Id": "bu_demo",
}


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

    response = client.post("/api/v1/demo/reset", json={}, headers=ADMIN_HEADERS)

    assert response.status_code == 403
    assert response.json()["code"] == "DEMO_RESET_DISABLED"


def test_demo_reset_runs_seed_script_for_admin(
    client: TestClient,
    monkeypatch,
) -> None:
    observed: dict[str, object] = {}

    def successful_run(command, **kwargs):
        observed["command"] = command
        observed["timeout"] = kwargs["timeout"]
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr(main_module.subprocess, "run", successful_run)

    response = client.post("/api/v1/demo/reset", json={}, headers=ADMIN_HEADERS)

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": "演示数据已检查并恢复",
    }
    command = observed["command"]
    assert isinstance(command, list)
    assert command[-1] == "http://127.0.0.1:8000"
    assert observed["timeout"] == 240


def test_demo_reset_rejects_overlapping_run(
    client: TestClient,
    monkeypatch,
) -> None:
    def unexpected_run(*args, **kwargs):
        raise AssertionError("seed script must not run while another reset is active")

    monkeypatch.setattr(main_module.subprocess, "run", unexpected_run)
    assert main_module.demo_reset_lock.acquire(blocking=False)
    try:
        response = client.post("/api/v1/demo/reset", json={}, headers=ADMIN_HEADERS)
    finally:
        main_module.demo_reset_lock.release()

    assert response.status_code == 409
    assert response.json()["code"] == "DEMO_RESET_IN_PROGRESS"


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

    response = client.post("/api/v1/demo/reset", json={}, headers=ADMIN_HEADERS)

    assert response.status_code == 500
    assert response.json()["code"] == "DEMO_RESET_FAILED"


def test_demo_reset_reports_timeout_and_releases_lock(
    client: TestClient,
    monkeypatch,
) -> None:
    def timed_out_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(main_module.subprocess, "run", timed_out_run)

    response = client.post("/api/v1/demo/reset", json={}, headers=ADMIN_HEADERS)

    assert response.status_code == 504
    assert response.json()["code"] == "DEMO_RESET_TIMEOUT"
    assert main_module.demo_reset_lock.acquire(blocking=False)
    main_module.demo_reset_lock.release()

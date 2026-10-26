from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from ticket_agent.shared.rate_limit import (
    reset_rate_limit_metrics,
    reset_rate_limits,
)
from ticket_agent.shared.settings import Settings


@pytest.fixture(autouse=True)
def clear_limits() -> Generator[None, None, None]:
    reset_rate_limits()
    reset_rate_limit_metrics()
    yield
    reset_rate_limits()
    reset_rate_limit_metrics()


def _enable_limit(monkeypatch: pytest.MonkeyPatch, limit: int) -> None:
    settings = Settings(
        rate_limit_enabled=True,
        rate_limit_backend="memory",
        rate_limit_window_seconds=60,
        rate_limit_requests_per_minute=limit,
    )
    monkeypatch.setattr(
        "ticket_agent.shared.rate_limit.get_settings",
        lambda: settings,
    )


def _search(client: TestClient, actor: str = "demo.agent") -> Response:
    return client.post(
        "/api/v1/knowledge/search",
        headers={"X-Actor-Id": actor, "X-Business-Unit-Id": "bu_demo"},
        json={
            "query": "如何给团队配置消息通知",
            "business_unit_id": "bu_demo",
            "top_k": 3,
        },
    )


def test_expensive_endpoint_returns_429_with_retry_after(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_limit(monkeypatch, limit=2)

    assert _search(client).status_code == 200
    assert _search(client).status_code == 200
    blocked = _search(client)

    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "60"
    body = blocked.json()
    assert body["code"] == "RATE_LIMITED"
    assert body["retryable"] is True
    assert body["context"]["retry_after_seconds"] == 60


def test_rate_limit_does_not_affect_other_actors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_limit(monkeypatch, limit=1)

    assert _search(client, actor="alpha.agent").status_code == 200
    assert _search(client, actor="alpha.agent").status_code == 429
    assert _search(client, actor="beta.agent").status_code == 200


def test_rate_limit_is_disabled_by_default(client: TestClient) -> None:
    for _ in range(3):
        assert _search(client).status_code == 200


def test_rejections_are_exported_to_prometheus(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_limit(monkeypatch, limit=1)

    assert _search(client).status_code == 200
    assert _search(client).status_code == 429

    metrics = client.get("/metrics")

    assert metrics.status_code == 200
    assert (
        "# TYPE ticket_worker_rate_limit_rejections_total counter"
        in metrics.text
    )
    assert "ticket_worker_rate_limit_rejections_total 1" in metrics.text

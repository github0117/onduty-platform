from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from ticket_agent.shared.settings import get_settings


def _use_limit(monkeypatch: pytest.MonkeyPatch, max_bytes: int) -> None:
    settings = get_settings().model_copy(update={"max_request_bytes": max_bytes})
    monkeypatch.setattr(
        "ticket_agent.shared.body_limit.get_settings",
        lambda: settings,
    )


def _search_payload() -> dict[str, object]:
    return {
        "query": "如何给团队配置消息通知",
        "business_unit_id": "bu_demo",
        "top_k": 3,
    }


def test_rejects_json_body_over_the_limit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_limit(monkeypatch, max_bytes=512)
    payload = _search_payload()
    payload["query"] = "通知" * 500

    response = client.post(
        "/api/v1/knowledge/search",
        headers={"Origin": "http://localhost:5173"},
        json=payload,
    )

    assert response.status_code == 413
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["x-correlation-id"]
    body = response.json()
    assert body["code"] == "PAYLOAD_TOO_LARGE"
    assert body["retryable"] is False
    assert body["context"]["max_request_bytes"] == 512


def test_rejects_chunked_body_without_content_length(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_limit(monkeypatch, max_bytes=512)

    def chunks() -> Iterator[bytes]:
        yield b'{"query":"' + b"a" * 600
        yield b'"}'

    response = client.post(
        "/api/v1/knowledge/search",
        headers={"Content-Type": "application/json"},
        content=chunks(),
    )

    assert "content-length" not in response.request.headers
    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"


def test_allows_body_within_the_limit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_limit(monkeypatch, max_bytes=4096)

    response = client.post("/api/v1/knowledge/search", json=_search_payload())

    assert response.status_code == 200


def test_limit_does_not_affect_bodyless_requests(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_limit(monkeypatch, max_bytes=1)

    response = client.get("/health/live")

    assert response.status_code == 200

from fastapi.testclient import TestClient

from ticket_agent.logistics.schemas import LogisticsQueryRequest
from ticket_agent.logistics.service import LogisticsQueryService
from ticket_agent.shared.settings import Settings

AGENT = {"X-Actor-Id": "logistics-agent", "X-Actor-Role": "agent"}


def test_logistics_query_is_explicit_when_provider_is_not_configured(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/logistics/query",
        headers=AGENT,
        json={"tracking_number": "SF1234567890", "carrier_code": "SF"},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "LOGISTICS_PROVIDER_NOT_CONFIGURED"


def test_http_logistics_response_is_normalized(
    monkeypatch,
) -> None:
    import httpx

    import ticket_agent.logistics.service as logistics_module

    def fake_post(*args: object, **kwargs: object) -> httpx.Response:
        del args, kwargs
        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://logistics.example/query"),
            json={
                "tracking_number": "SF1234567890",
                "carrier_code": "SF",
                "status": "IN_TRANSIT",
                "latest_event_at": "2026-10-24T12:00:00Z",
                "events": [
                    {
                        "occurred_at": "2026-10-24T12:00:00Z",
                        "location": "杭州转运中心",
                        "description": "快件已到达转运中心",
                    }
                ],
            },
        )

    monkeypatch.setattr(logistics_module.httpx, "post", fake_post)
    service = LogisticsQueryService(
        Settings(
            logistics_query_provider="http_json",
            logistics_query_base_url="https://logistics.example/query",
        )
    )

    result = service.query(
        LogisticsQueryRequest(
            tracking_number="SF1234567890",
            carrier_code="SF",
        )
    )

    assert result.status == "IN_TRANSIT"
    assert result.status_label == "运输中"
    assert result.events[0].location == "杭州转运中心"
    assert result.latest_event_at is not None

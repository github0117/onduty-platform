import json

import httpx
import pytest

from ticket_agent.integrations.http_json import HTTPJSONTicketAdapter
from ticket_agent.integrations.types import TicketIntegrationError, TicketSyncPayload
from ticket_agent.shared.settings import Settings


def _payload() -> TicketSyncPayload:
    return TicketSyncPayload(
        external_ticket_id="HD-001",
        category_primary="product_howto",
        category_secondary="configuration",
        priority="P3",
        risk_level="R0",
        queue_id="PRODUCT_SUPPORT",
        response_text="请进入设置中心配置。",
        citations=[{"chunk_id": "chunk-1"}],
    )


def test_http_ticket_adapter_sends_idempotent_json_update() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["headers"] = request.headers
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, headers={"X-Request-ID": "ext-123"})

    settings = Settings(
        ticket_integration_provider="http_json",
        ticket_api_base_url="https://tickets.example/api",
        ticket_api_key="ticket-secret",
    )
    adapter = HTTPJSONTicketAdapter(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.sync_ticket(
        payload=_payload(),
        idempotency_key="ticket-sync:001",
    )

    assert captured["path"] == "/api/tickets/HD-001"
    assert captured["headers"]["Idempotency-Key"] == "ticket-sync:001"
    assert captured["headers"]["Authorization"] == "Bearer ticket-secret"
    assert captured["body"]["queue_id"] == "PRODUCT_SUPPORT"
    assert result.external_request_id == "ext-123"


def test_http_ticket_adapter_classifies_retryable_failure() -> None:
    settings = Settings(
        ticket_integration_provider="http_json",
        ticket_api_base_url="https://tickets.example/api",
    )
    adapter = HTTPJSONTicketAdapter(
        settings,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(503)
            )
        ),
    )

    with pytest.raises(TicketIntegrationError) as error:
        adapter.sync_ticket(payload=_payload(), idempotency_key="key")

    assert error.value.retryable is True


def test_http_ticket_adapter_resolves_409_by_idempotency_lookup() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "PUT":
            return httpx.Response(409)
        return httpx.Response(200, json={"request_id": "existing-123"})

    settings = Settings(
        ticket_integration_provider="http_json",
        ticket_api_base_url="https://tickets.example/api",
    )
    adapter = HTTPJSONTicketAdapter(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.sync_ticket(
        payload=_payload(),
        idempotency_key="ticket-sync:001",
    )

    assert [request.method for request in requests] == ["PUT", "GET"]
    assert requests[1].url.path.endswith("/tickets/HD-001/sync-results/ticket-sync:001")
    assert result.external_request_id == "existing-123"


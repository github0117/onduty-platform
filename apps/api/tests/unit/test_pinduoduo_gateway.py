from urllib.parse import parse_qs

import httpx

from ticket_agent.ecommerce.pinduoduo_gateway import (
    PinduoduoGatewayClient,
    sign_pinduoduo_params,
)
from ticket_agent.shared.settings import Settings


def test_pinduoduo_signature_and_time_request() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        parsed = parse_qs(request.content.decode("utf-8"))
        captured.update({key: values[0] for key, values in parsed.items()})
        return httpx.Response(
            200,
            json={"time_get_response": {"time": "2026-10-24 15:00:00"}},
        )

    settings = Settings(
        pinduoduo_client_id="client-id",
        pinduoduo_client_secret="client-secret",
        pinduoduo_access_token="access-token",
        pinduoduo_api_base_url="https://pdd.example/api/router",
    )
    gateway = PinduoduoGatewayClient(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: 1_700_000_000,
    )

    result = gateway.test_connection()

    assert result.api_type == "pdd.time.get"
    assert captured["type"] == "pdd.time.get"
    assert captured["client_id"] == "client-id"
    assert captured["access_token"] == "access-token"
    assert captured["timestamp"] == "1700000000"
    expected_signature = sign_pinduoduo_params(
        {
            key: value
            for key, value in captured.items()
            if key != "sign"
        },
        "client-secret",
    )
    assert captured["sign"] == expected_signature


def test_pinduoduo_gateway_reports_missing_credentials() -> None:
    gateway = PinduoduoGatewayClient(Settings())

    assert gateway.configured is False


def test_pinduoduo_app_can_test_connection_without_merchant_token() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        parsed = parse_qs(request.content.decode("utf-8"))
        captured.update({key: values[0] for key, values in parsed.items()})
        return httpx.Response(
            200,
            json={"time_get_response": {"time": "2026-10-24 15:00:00"}},
        )

    gateway = PinduoduoGatewayClient(
        Settings(
            pinduoduo_client_id="client-id",
            pinduoduo_client_secret="client-secret",
            pinduoduo_access_token="",
        ),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: 1_700_000_000,
    )

    result = gateway.test_connection()

    assert result.api_type == "pdd.time.get"
    assert gateway.configured is True
    assert gateway.merchant_authorized is False
    assert "access_token" not in captured

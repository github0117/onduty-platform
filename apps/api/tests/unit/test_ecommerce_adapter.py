import json
from uuid import uuid4

import httpx
import pytest

from ticket_agent.ecommerce.adapters import (
    EcommerceChannelError,
    EcommerceListingPayload,
    HTTPJSONEcommerceChannelAdapter,
)
from ticket_agent.shared.settings import Settings


def _payload() -> EcommerceListingPayload:
    return EcommerceListingPayload(
        task_id=uuid4(),
        sku="SKU-001",
        channel="local_shop",
        product_name="测试商品",
        category="家居日用",
        price=39.9,
        attributes={"材质": "不锈钢"},
        content={"title": "测试商品"},
        asset_ids=["asset-1"],
    )


def test_http_ecommerce_adapter_publishes_listing() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["idempotency"] = request.headers["Idempotency-Key"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"listing_id": "CHANNEL-123"})

    adapter = HTTPJSONEcommerceChannelAdapter(
        Settings(
            ecommerce_channel_provider="http_json",
            ecommerce_channel_base_url="https://commerce.example/v1",
            ecommerce_channel_api_key="test-key",
        ),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    payload = _payload()

    result = adapter.publish(payload)

    assert result.external_listing_id == "CHANNEL-123"
    assert captured["method"] == "PUT"
    assert captured["path"] == "/v1/channels/local_shop/listings/SKU-001"
    assert captured["idempotency"] == f"ecommerce-listing:{payload.task_id}"
    assert captured["body"]["asset_ids"] == ["asset-1"]


def test_http_ecommerce_adapter_marks_server_error_retryable() -> None:
    adapter = HTTPJSONEcommerceChannelAdapter(
        Settings(
            ecommerce_channel_provider="http_json",
            ecommerce_channel_base_url="https://commerce.example/v1",
        ),
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(503))
        ),
    )

    with pytest.raises(EcommerceChannelError) as error:
        adapter.publish(_payload())

    assert error.value.retryable is True

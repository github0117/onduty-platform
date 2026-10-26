from types import SimpleNamespace

import pytest

import ticket_agent.customer_service.business_context as context_module
from ticket_agent.customer_service.business_context import (
    CustomerBusinessContextService,
)
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import Settings


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "customer": {
                "customer_ref": "demo.order.customer",
                "display_name": "演示客户",
                "tier": "standard",
                "joined_at": "2026-09-18T09:30:00+08:00",
            },
            "order": {
                "order_id": "MOCK-ORD-1001",
                "customer_ref": "demo.order.customer",
                "status": "SHIPPED",
                "status_label": "已发货",
                "item_name": "316 不锈钢保温杯",
                "amount": 129.0,
                "currency": "CNY",
                "order_version": 3,
                "shipping_address": {
                    "recipient": "王女士",
                    "phone": "13800001234",
                    "province": "浙江省",
                    "city": "杭州市",
                    "district": "西湖区",
                    "detail": "文一西路 100 号 2 幢 501",
                },
                "after_sales_cases": [],
            },
            "resolution": {
                "confidence": 0.98,
                "matched_by": "订单号",
                "warnings": [],
            },
            "source": "mock-business",
        }


def test_business_context_extracts_order_and_masks_phone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_get(
        url: str,
        *,
        params: dict[str, str] | None,
        timeout: float,
    ) -> FakeResponse:
        captured.update(
            {
                "url": url,
                "params": params,
                "timeout": timeout,
            }
        )
        return FakeResponse()

    monkeypatch.setattr(context_module.httpx, "get", fake_get)
    service = CustomerBusinessContextService(
        settings=Settings(
            business_sandbox_provider="http_json",
            business_sandbox_base_url="http://business-sandbox",
            business_sandbox_timeout_seconds=3,
        )
    )
    conversation = SimpleNamespace(
        requester_ref="demo.order.customer",
    )
    messages = [
        SimpleNamespace(
            content="订单 MOCK-ORD-1001 还没送到，我想修改收货地址。",
        )
    ]

    result = service.resolve(conversation, messages)  # type: ignore[arg-type]

    assert captured["url"] == (
        "http://business-sandbox/customers/"
        "demo.order.customer/business-context"
    )
    assert captured["params"] == {"order_id": "MOCK-ORD-1001"}
    assert result.order.order_id == "MOCK-ORD-1001"
    assert result.order.shipping_address.phone == "138****1234"
    assert result.resolution.confidence == 0.98


def test_business_context_refuses_unconfigured_sandbox() -> None:
    service = CustomerBusinessContextService(
        settings=Settings(
            business_sandbox_provider="none",
            business_sandbox_base_url="",
        )
    )

    with pytest.raises(ApiProblem) as exc_info:
        service.resolve(  # type: ignore[arg-type]
            SimpleNamespace(requester_ref="demo.order.customer"),
            [],
        )

    assert exc_info.value.code == "BUSINESS_SANDBOX_NOT_CONFIGURED"

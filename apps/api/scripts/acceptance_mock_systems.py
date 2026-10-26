#!/usr/bin/env python3
import json
import sys
from uuid import uuid4

import httpx

from ticket_agent.ecommerce.adapters import (
    EcommerceChannelError,
    EcommerceListingPayload,
    HTTPJSONEcommerceChannelAdapter,
)
from ticket_agent.integrations.http_json import HTTPJSONTicketAdapter
from ticket_agent.integrations.types import (
    TicketIntegrationError,
    TicketSyncPayload,
)
from ticket_agent.logistics.schemas import LogisticsQueryRequest
from ticket_agent.logistics.service import LogisticsQueryService
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import Settings


def main() -> None:
    base_url = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "http://mock-business:8090"
    ).rstrip("/")
    settings = Settings(
        ticket_integration_provider="http_json",
        ticket_api_base_url=base_url,
        ecommerce_channel_provider="http_json",
        ecommerce_channel_base_url=base_url,
        logistics_query_provider="http_json",
        logistics_query_base_url=f"{base_url}/logistics/queries",
    )
    suffix = uuid4().hex[:8]
    ticket_adapter = HTTPJSONTicketAdapter(settings)
    ticket_payload = TicketSyncPayload(
        external_ticket_id=f"MOCK-TICKET-{suffix}",
        category_primary="product_howto",
        category_secondary="configuration",
        priority="P3",
        risk_level="R0",
        queue_id="PRODUCT_SUPPORT",
        response_text="模拟回复",
        citations=[{"title": "模拟知识", "version": "1.0"}],
    )
    first = ticket_adapter.sync_ticket(
        payload=ticket_payload,
        idempotency_key=f"ticket:{suffix}",
    )
    second = ticket_adapter.sync_ticket(
        payload=ticket_payload,
        idempotency_key=f"ticket:{suffix}",
    )
    if first.external_request_id != second.external_request_id:
        raise RuntimeError("Ticket idempotency returned different request IDs")

    ticket_failure = _expect_ticket_failure(
        ticket_adapter,
        TicketSyncPayload(
            external_ticket_id=f"FAIL500-{suffix}",
            category_primary="other_unclassified",
            category_secondary="unknown",
            priority="P2",
            risk_level="R1",
            queue_id="MANUAL_TRIAGE",
            response_text="",
            citations=[],
        ),
    )

    channel_adapter = HTTPJSONEcommerceChannelAdapter(settings)
    listing = channel_adapter.publish(
        EcommerceListingPayload(
            task_id=uuid4(),
            sku=f"MOCK-SKU-{suffix}",
            channel="mock_shop",
            product_name="模拟商品",
            category="模拟品类",
            price=59.9,
            attributes={"material": "mock"},
            content={"title": "模拟标题"},
            asset_ids=[],
        )
    )
    channel_failure = _expect_channel_failure(channel_adapter, suffix)

    logistics = LogisticsQueryService(settings)
    shipment = logistics.query(
        LogisticsQueryRequest(order_id=f"ORDER-{suffix}")
    )
    logistics_failure = _expect_logistics_failure(logistics, suffix)

    with httpx.Client(base_url=base_url, timeout=10) as client:
        employee = client.get(f"/employees/EMP-{suffix}")
        employee.raise_for_status()
        order = client.get(f"/orders/ORDER-{suffix}")
        order.raise_for_status()
        refund = client.post(
            "/refunds",
            headers={"Idempotency-Key": f"refund:{suffix}"},
            json={
                "order_id": f"ORDER-{suffix}",
                "amount": 59.9,
                "reason": "模拟质量原因",
            },
        )
        refund.raise_for_status()

    print(
        json.dumps(
            {
                "mock_base_url": base_url,
                "employee": employee.json()["name"],
                "order_status": order.json()["status"],
                "logistics_status": shipment.status,
                "ticket_request_id": first.external_request_id,
                "ticket_failure_retryable": ticket_failure,
                "listing_id": listing.external_listing_id,
                "channel_failure_retryable": channel_failure,
                "logistics_failure": logistics_failure,
                "refund_id": refund.json()["refund_id"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _expect_ticket_failure(
    adapter: HTTPJSONTicketAdapter,
    payload: TicketSyncPayload,
) -> bool:
    try:
        adapter.sync_ticket(
            payload=payload,
            idempotency_key="failure-ticket",
        )
    except TicketIntegrationError as exc:
        if not exc.retryable:
            raise RuntimeError("HTTP 500 ticket failure must be retryable") from exc
        return True
    raise RuntimeError("Ticket failure mode unexpectedly succeeded")


def _expect_channel_failure(
    adapter: HTTPJSONEcommerceChannelAdapter,
    suffix: str,
) -> bool:
    try:
        adapter.publish(
            EcommerceListingPayload(
                task_id=uuid4(),
                sku=f"FAIL500-{suffix}",
                channel="mock_shop",
                product_name="失败商品",
                category="模拟品类",
                price=59.9,
                attributes={},
                content={},
                asset_ids=[],
            )
        )
    except EcommerceChannelError as exc:
        if not exc.retryable:
            raise RuntimeError("HTTP 500 channel failure must be retryable") from exc
        return True
    raise RuntimeError("Channel failure mode unexpectedly succeeded")


def _expect_logistics_failure(
    service: LogisticsQueryService,
    suffix: str,
) -> str:
    try:
        service.query(LogisticsQueryRequest(order_id=f"FAIL500-{suffix}"))
    except ApiProblem as exc:
        return exc.code
    raise RuntimeError("Logistics failure mode unexpectedly succeeded")


if __name__ == "__main__":
    main()

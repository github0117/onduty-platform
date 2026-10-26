#!/usr/bin/env python3
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

business_base_url = os.getenv(
    "MOCK_BUSINESS_BASE_URL",
    "http://127.0.0.1:8090",
).rstrip("/")

mcp = FastMCP(
    "Demo Business Sandbox",
    instructions=(
        "Deterministic customer, order, logistics and address-change sandbox. "
        "Write actions are approval-gated by the calling platform."
    ),
    host="0.0.0.0",
    port=8091,
    streamable_http_path="/mcp",
    json_response=True,
    stateless_http=True,
)


@mcp.tool()
def get_customer_business_context(
    customer_ref: str,
    order_id: str | None = None,
) -> dict[str, Any]:
    """Resolve the customer, current order, logistics and after-sales context."""
    params = {"order_id": order_id} if order_id else None
    return _get(
        f"/customers/{customer_ref}/business-context",
        params=params,
    )


@mcp.tool()
def get_logistics(order_id: str) -> dict[str, Any]:
    """Query the current shipment and latest logistics events."""
    return _post(
        "/logistics/queries",
        {"order_id": order_id},
    )


@mcp.tool()
def change_shipping_address(
    order_id: str,
    recipient: str,
    phone: str,
    province: str,
    city: str,
    district: str,
    detail: str,
    expected_order_version: int,
    idempotency_key: str,
    reason: str,
) -> dict[str, Any]:
    """Change a shipment address after platform approval."""
    return _post(
        f"/orders/{order_id}/address-changes",
        {
            "new_address": {
                "recipient": recipient,
                "phone": phone,
                "province": province,
                "city": city,
                "district": district,
                "detail": detail,
            },
            "expected_order_version": expected_order_version,
            "reason": reason,
        },
        headers={"Idempotency-Key": idempotency_key},
        timeout=10,
    )


@mcp.tool()
def get_address_change_status(
    order_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Read the actual address-change result for reconciliation."""
    return _get(
        f"/orders/{order_id}/address-changes/{idempotency_key}",
    )


def _get(
    path: str,
    *,
    params: dict[str, object] | None = None,
) -> dict[str, Any]:
    response = httpx.get(
        f"{business_base_url}{path}",
        params=params,
        timeout=5,
    )
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError("Business sandbox must return a JSON object")
    return body


def _post(
    path: str,
    payload: dict[str, object],
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 5,
) -> dict[str, Any]:
    response = httpx.post(
        f"{business_base_url}{path}",
        json=payload,
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError("Business sandbox must return a JSON object")
    return body


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

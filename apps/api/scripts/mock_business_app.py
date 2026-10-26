#!/usr/bin/env python3
import time
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

app = FastAPI(title="Mock Business Systems")

_ticket_results: dict[str, dict[str, Any]] = {}
_listing_results: dict[str, dict[str, Any]] = {}
_refunds: dict[str, dict[str, Any]] = {}
_address_change_lock = Lock()
_customers: dict[str, dict[str, Any]] = {
    "demo.order.customer": {
        "customer_ref": "demo.order.customer",
        "display_name": "演示客户",
        "tier": "standard",
        "joined_at": "2026-09-18T09:30:00+08:00",
    }
}
_orders: dict[str, dict[str, Any]] = {
    "MOCK-ORD-1001": {
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
        "logistics_status": "IN_TRANSIT",
        "logistics_status_label": "运输中",
        "after_sales_cases": [
            {
                "case_id": "MOCK-AS-1001",
                "case_type": "物流咨询",
                "status": "OPEN",
                "status_label": "处理中",
                "summary": "客户正在确认配送进度和收货安排",
            }
        ],
        "created_at": "2026-10-22T10:20:00+08:00",
    }
}
_address_changes: dict[str, dict[str, Any]] = {}


class LogisticsQuery(BaseModel):
    order_id: str | None = None
    tracking_number: str | None = None
    carrier_code: str | None = None


class RefundRequest(BaseModel):
    order_id: str
    amount: float
    reason: str


class Address(BaseModel):
    recipient: str
    phone: str
    province: str
    city: str
    district: str
    detail: str


class AddressChangeRequest(BaseModel):
    new_address: Address
    expected_order_version: int
    reason: str = ""


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "simulation"}


@app.get("/employees/{employee_id}")
def get_employee(employee_id: str) -> dict[str, Any]:
    if "NOT_FOUND" in employee_id:
        raise HTTPException(status_code=404, detail="Employee not found")
    return {
        "employee_id": employee_id,
        "name": "模拟员工",
        "department": "企业服务部",
        "status": "ACTIVE",
    }


@app.get("/orders/{order_id}")
def get_order(order_id: str) -> dict[str, Any]:
    if "FAIL500" in order_id:
        raise HTTPException(status_code=500, detail="Simulated order failure")
    return _ensure_order(order_id)


@app.get("/customers/{customer_ref}/business-context")
def get_business_context(
    customer_ref: str,
    order_id: str | None = Query(default=None),
) -> dict[str, Any]:
    if "NOT_FOUND" in customer_ref:
        raise HTTPException(status_code=404, detail="Customer not found")
    customer = _customers.get(customer_ref)
    order = _find_order(customer_ref=customer_ref, order_id=order_id)
    if customer is None and order is None:
        raise HTTPException(status_code=404, detail="Customer context not found")
    if customer is None and order is not None:
        customer = {
            "customer_ref": customer_ref,
            "display_name": "演示客户",
            "tier": "standard",
            "joined_at": "2026-10-01T09:00:00+08:00",
        }
    if order is None and customer is not None:
        order = _ensure_order("MOCK-ORD-1001", customer_ref=customer_ref)
    return {
        "customer": customer,
        "order": order,
        "resolution": {
            "confidence": 0.98 if order_id else 0.91,
            "matched_by": "订单号" if order_id else "客户最近订单",
            "warnings": [] if order else ["未找到可用订单"],
        },
        "source": "mock-business",
    }


@app.post("/orders/{order_id}/address-changes")
def create_address_change(
    order_id: str,
    payload: AddressChangeRequest,
    idempotency_key: str | None = Header(default=None),
) -> dict[str, Any]:
    key = idempotency_key or (
        f"mock-address:{order_id}:"
        f"{payload.new_address.model_dump_json()}:"
        f"{payload.expected_order_version}"
    )
    with _address_change_lock:
        existing = _address_changes.get(key)
        if existing is not None:
            return existing
        order = _ensure_order(order_id)
        if order["status"] in {"DELIVERED", "CANCELLED"}:
            raise HTTPException(
                status_code=409,
                detail="Order cannot change address in current status",
            )
        if payload.expected_order_version != order["order_version"]:
            raise HTTPException(status_code=409, detail="Order version conflict")
        if "REJECT" in key.upper():
            raise HTTPException(
                status_code=409,
                detail="Carrier rejected the address change",
            )
        result = {
            "request_id": f"MOCK-ADDR-{len(_address_changes) + 1}",
            "order_id": order_id,
            "status": "APPLIED",
            "status_label": "地址已修改",
            "idempotency_key": key,
            "order_version": order["order_version"] + 1,
            "shipping_address": payload.new_address.model_dump(),
            "completed_at": datetime.now(UTC).isoformat(),
        }
        order["shipping_address"] = payload.new_address.model_dump()
        order["order_version"] += 1
        _address_changes[key] = result
    if "TIMEOUT" in key.upper():
        time.sleep(4)
    return result


@app.get("/orders/{order_id}/address-changes/{idempotency_key}")
def get_address_change(
    order_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    result = _address_changes.get(idempotency_key)
    if result is None or result["order_id"] != order_id:
        return {
            "order_id": order_id,
            "idempotency_key": idempotency_key,
            "status": "NOT_EXECUTED",
            "status_label": "未执行",
            "checked_at": datetime.now(UTC).isoformat(),
        }
    return result


@app.post("/logistics/queries")
def query_logistics(payload: LogisticsQuery) -> Any:
    identifier = payload.order_id or payload.tracking_number or ""
    if "FAIL500" in identifier:
        raise HTTPException(status_code=500, detail="Simulated logistics failure")
    if "MALFORMED" in identifier:
        return PlainTextResponse("not-json", status_code=200)
    return {
        "order_id": payload.order_id,
        "tracking_number": payload.tracking_number or "MOCK-TRACK-001",
        "carrier_code": payload.carrier_code or "MOCK-EXPRESS",
        "status": "IN_TRANSIT",
        "status_label": "运输中",
        "latest_event_at": datetime.now(UTC).isoformat(),
        "events": [
            {
                "occurred_at": datetime.now(UTC).isoformat(),
                "location": "模拟转运中心",
                "description": "模拟物流轨迹已更新",
            }
        ],
    }


@app.put("/tickets/{external_ticket_id}")
def upsert_ticket(
    external_ticket_id: str,
    payload: dict[str, Any],
    idempotency_key: str | None = Header(default=None),
) -> dict[str, Any]:
    if "FAIL500" in external_ticket_id:
        raise HTTPException(status_code=500, detail="Simulated ticket failure")
    key = idempotency_key or f"mock-ticket:{external_ticket_id}"
    existing = _ticket_results.get(key)
    if existing is not None:
        return existing
    result = {
        "request_id": f"MOCK-TICKET-{len(_ticket_results) + 1}",
        "external_ticket_id": external_ticket_id,
        "payload": payload,
    }
    _ticket_results[key] = result
    return result


@app.get("/tickets/{external_ticket_id}/sync-results/{idempotency_key}")
def get_ticket_result(
    external_ticket_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    result = _ticket_results.get(idempotency_key)
    if result is None or result["external_ticket_id"] != external_ticket_id:
        raise HTTPException(status_code=404, detail="Sync result not found")
    return result


@app.put("/channels/{channel}/listings/{sku}")
def publish_listing(
    channel: str,
    sku: str,
    payload: dict[str, Any],
    idempotency_key: str | None = Header(default=None),
) -> Any:
    if "FAIL500" in sku:
        raise HTTPException(status_code=500, detail="Simulated publish failure")
    if "MALFORMED" in sku:
        return PlainTextResponse("not-json", status_code=200)
    key = idempotency_key or f"mock-listing:{channel}:{sku}"
    existing = _listing_results.get(key)
    if existing is not None:
        return existing
    result = {
        "listing_id": f"MOCK-LISTING-{len(_listing_results) + 1}",
        "channel": channel,
        "sku": sku,
        "payload": payload,
    }
    _listing_results[key] = result
    return result


@app.post("/refunds")
def create_refund(
    payload: RefundRequest,
    idempotency_key: str | None = Header(default=None),
) -> dict[str, Any]:
    key = idempotency_key or (
        f"mock-refund:{payload.order_id}:{payload.amount}:{payload.reason}"
    )
    existing = _refunds.get(key)
    if existing is not None:
        return existing
    result = {
        "refund_id": f"MOCK-REFUND-{len(_refunds) + 1}",
        "status": "ACCEPTED",
        **payload.model_dump(),
    }
    _refunds[key] = result
    return result


@app.get("/state")
def state() -> JSONResponse:
    return JSONResponse(
        {
            "tickets": len(_ticket_results),
            "listings": len(_listing_results),
            "refunds": len(_refunds),
            "address_changes": len(_address_changes),
        }
    )


def _find_order(
    *,
    customer_ref: str,
    order_id: str | None,
) -> dict[str, Any] | None:
    if order_id:
        order = _ensure_order(order_id, customer_ref=customer_ref)
        return order if order["customer_ref"] == customer_ref else None
    return next(
        (
            order
            for order in _orders.values()
            if order["customer_ref"] == customer_ref
        ),
        None,
    )


def _ensure_order(
    order_id: str,
    *,
    customer_ref: str = "demo.order.customer",
) -> dict[str, Any]:
    existing = _orders.get(order_id)
    if existing is not None:
        return existing
    order = {
        "order_id": order_id,
        "customer_ref": customer_ref,
        "status": "SHIPPED",
        "status_label": "已发货",
        "item_name": "演示订单商品",
        "amount": 99.0,
        "currency": "CNY",
        "order_version": 1,
        "shipping_address": {
            "recipient": "演示客户",
            "phone": "13800000000",
            "province": "浙江省",
            "city": "杭州市",
            "district": "西湖区",
            "detail": "演示路 1 号",
        },
        "logistics_status": "IN_TRANSIT",
        "logistics_status_label": "运输中",
        "after_sales_cases": [],
        "created_at": datetime.now(UTC).isoformat(),
    }
    _orders[order_id] = order
    return order

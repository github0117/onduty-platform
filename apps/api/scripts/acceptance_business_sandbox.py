#!/usr/bin/env python3
import json
import sys
import time
from datetime import UTC, datetime

import httpx


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    base_headers = {"X-Business-Unit-Id": "bu_demo"}
    agent = {
        **base_headers,
        "X-Actor-Id": "demo.agent",
        "X-Actor-Role": "agent",
    }
    supervisor = {
        **base_headers,
        "X-Actor-Id": "demo.supervisor",
        "X-Actor-Role": "supervisor",
    }
    admin = {
        **base_headers,
        "X-Actor-Id": "demo.admin",
        "X-Actor-Role": "admin",
    }
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    order_id = f"MOCK-ORD-ACCEPT-{suffix}"
    requester_ref = f"address-acceptance-{suffix}"
    conversation_id = ""
    ticket_id = ""
    try:
        with httpx.Client(base_url=base_url, timeout=40) as client:
            client.get("/health/ready").raise_for_status()
            employees = client.get(
                "/api/v1/digital-employees",
                headers=admin,
                params={"business_unit_id": "bu_demo"},
            )
            employees.raise_for_status()
            employee = next(
                item
                for item in employees.json()
                if item["employee_key"]
                == "demo_vacuum_cup_customer_service"
            )
            conversation = client.post(
                "/api/v1/customer-service/conversations",
                headers=agent,
                json={
                    "business_unit_id": "bu_demo",
                    "employee_id": employee["id"],
                    "requester_ref": requester_ref,
                    "category_name": "保温杯",
                    "channel": "web_form",
                },
            )
            conversation.raise_for_status()
            conversation_id = conversation.json()["id"]
            message = client.post(
                (
                    "/api/v1/customer-service/conversations/"
                    f"{conversation_id}/messages"
                ),
                headers=agent,
                json={
                    "content": (
                        f"订单 {order_id} 还没送到，我想修改收货地址"
                    ),
                },
            )
            message.raise_for_status()
            ticket_id = message.json()["current_ticket_id"]
            ticket = _wait_for_address_ticket(
                client,
                ticket_id=ticket_id,
                headers=agent,
            )
            current = client.get(
                (
                    "/api/v1/customer-service/conversations/"
                    f"{conversation_id}"
                ),
                headers=agent,
            )
            current.raise_for_status()
            assigned_agent = current.json().get("assigned_agent_id")
            if assigned_agent is None:
                takeover = client.post(
                    (
                        "/api/v1/customer-service/conversations/"
                        f"{conversation_id}/takeover"
                    ),
                    headers=agent,
                    json={
                        "expected_version": current.json()["version"],
                    },
                )
                takeover.raise_for_status()
                assigned_agent = takeover.json()["assigned_agent_id"]
            assert assigned_agent
            action_actor = {
                **base_headers,
                "X-Actor-Id": assigned_agent,
                "X-Actor-Role": "admin",
            }
            approver = (
                admin
                if assigned_agent == supervisor["X-Actor-Id"]
                else supervisor
            )
            context = client.get(
                (
                    "/api/v1/customer-service/conversations/"
                    f"{conversation_id}/business-context"
                ),
                headers=action_actor,
                params={"order_id": order_id},
            )
            context.raise_for_status()
            order = context.json()["order"]
            action_payload = {
                "order_id": order_id,
                "expected_order_version": order["order_version"],
                "recipient": "李女士",
                "phone": "13900001234",
                "province": "浙江省",
                "city": "杭州市",
                "district": "滨江区",
                "detail": "江南大道 88 号 6 幢 1202",
                "reason": "客户搬家需要修改收货地址",
                "simulation_mode": "normal",
            }
            first = _request_action(
                client,
                conversation_id=conversation_id,
                headers=action_actor,
                payload=action_payload,
            )
            repeated = _request_action(
                client,
                conversation_id=conversation_id,
                headers=action_actor,
                payload=action_payload,
            )
            assert first["approval_id"]
            assert first["approval_id"] == repeated["approval_id"]
            approved = _approve(
                client,
                approval_id=first["approval_id"],
                headers=approver,
                note="已核对客户和订单，同意修改地址",
            )
            assert approved["status"] == "SUCCEEDED", approved
            changed = client.get(
                (
                    "/api/v1/customer-service/conversations/"
                    f"{conversation_id}/business-context"
                ),
                headers=action_actor,
                params={"order_id": order_id},
            )
            changed.raise_for_status()
            changed_order = changed.json()["order"]
            assert changed_order["shipping_address"]["detail"] == (
                "江南大道 88 号 6 幢 1202"
            )

            timeout_request = _request_action(
                client,
                conversation_id=conversation_id,
                headers=action_actor,
                payload={
                    **action_payload,
                    "expected_order_version": changed_order["order_version"],
                    "detail": "江陵路 99 号 1 幢 801",
                    "simulation_mode": "timeout_unknown",
                },
            )
            timed_out = _approve(
                client,
                approval_id=timeout_request["approval_id"],
                headers=approver,
                note="执行超时故障演练",
            )
            assert timed_out["status"] == "FAILED", timed_out
            incident = _find_incident(
                client,
                approval_id=timeout_request["approval_id"],
                headers=approver,
            )
            assert incident["failure_class"] == "EXECUTION_UNKNOWN"
            time.sleep(4)
            reconciled = client.post(
                (
                    "/api/v1/mcp/action-incidents/"
                    f"{incident['id']}/reconcile"
                ),
                headers=approver,
                json={"expected_version": incident["version"]},
            )
            reconciled.raise_for_status()
            reconciliation = reconciled.json()
            assert reconciliation["reconciliation_status"] == "SUCCEEDED"
            assert "APPLIED" in reconciliation["reconciliation_result"]["text"]
            resolved = client.post(
                (
                    "/api/v1/mcp/action-incidents/"
                    f"{incident['id']}/resolve"
                ),
                headers=approver,
                json={
                    "expected_version": reconciliation["version"],
                    "outcome": "EXECUTED_AS_INTENDED",
                    "note": "只读查询确认改址已生效，关闭本次故障演练。",
                },
            )
            resolved.raise_for_status()
            assert resolved.json()["status"] == "RESOLVED"

            print(
                json.dumps(
                    {
                        "conversation_id": conversation_id,
                        "ticket_id": ticket_id,
                        "order_id": order_id,
                        "classification": ticket["classification"],
                        "risk_level": ticket["risk"]["level"],
                        "assigned_agent_id": assigned_agent,
                        "address_change_approval": approved["status"],
                        "updated_address": changed_order["shipping_address"][
                            "detail"
                        ],
                        "timeout_approval": timed_out["status"],
                        "incident_class": incident["failure_class"],
                        "reconciliation": reconciliation[
                            "reconciliation_status"
                        ],
                        "incident_status": resolved.json()["status"],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
    finally:
        with httpx.Client(base_url=base_url, timeout=30) as client:
            if conversation_id:
                client.post(
                    (
                        "/api/v1/customer-service/conversations/"
                        f"{conversation_id}/archive-test-data"
                    ),
                    headers=admin,
                )
            if ticket_id:
                client.post(
                    f"/api/v1/tickets/{ticket_id}/archive-test-data",
                    headers=admin,
                )


def _wait_for_address_ticket(
    client: httpx.Client,
    *,
    ticket_id: str,
    headers: dict[str, str],
) -> dict[str, object]:
    deadline = time.monotonic() + 25
    ticket: dict[str, object] = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/tickets/{ticket_id}", headers=headers)
        response.raise_for_status()
        ticket = response.json()
        classification = ticket.get("classification")
        risk = ticket.get("risk")
        if (
            isinstance(classification, dict)
            and classification.get("secondary") == "address_change"
            and isinstance(risk, dict)
            and risk.get("level") == "R2"
        ):
            return ticket
        time.sleep(0.5)
    raise TimeoutError(f"Address-change ticket was not ready: {ticket}")


def _request_action(
    client: httpx.Client,
    *,
    conversation_id: str,
    headers: dict[str, str],
    payload: dict[str, object],
) -> dict[str, object]:
    response = client.post(
        (
            "/api/v1/customer-service/conversations/"
            f"{conversation_id}/business-actions/address-change"
        ),
        headers=headers,
        json=payload,
    )
    response.raise_for_status()
    body = response.json()
    assert body["status"] == "APPROVAL_REQUIRED", body
    return body


def _approve(
    client: httpx.Client,
    *,
    approval_id: str,
    headers: dict[str, str],
    note: str,
) -> dict[str, object]:
    approvals = client.get(
        "/api/v1/mcp/tool-approvals",
        headers=headers,
        params={"business_unit_id": "bu_demo", "limit": 200},
    )
    approvals.raise_for_status()
    approval = next(
        item
        for item in approvals.json()["items"]
        if item["id"] == approval_id
    )
    decision = client.post(
        f"/api/v1/mcp/tool-approvals/{approval_id}/decisions",
        headers=headers,
        json={
            "decision": "APPROVE",
            "expected_version": approval["version"],
            "note": note,
        },
    )
    decision.raise_for_status()
    return decision.json()


def _find_incident(
    client: httpx.Client,
    *,
    approval_id: str,
    headers: dict[str, str],
) -> dict[str, object]:
    response = client.get(
        "/api/v1/mcp/action-incidents",
        headers=headers,
        params={"business_unit_id": "bu_demo", "status": "OPEN"},
    )
    response.raise_for_status()
    return next(
        item
        for item in response.json()["items"]
        if item["approval_id"] == approval_id
    )


if __name__ == "__main__":
    main()

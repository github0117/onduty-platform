from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ticket_agent.customer_service import suggestions as suggestion_module
from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.mcp_connectors.models import McpConnector, McpToolApproval
from ticket_agent.mcp_connectors.runtime import McpToolRuntime
from ticket_agent.model_gateway.types import ToolPlan
from ticket_agent.shared.db import SessionLocal
from ticket_agent.tickets.models import Ticket
from ticket_agent.tools.models import ToolCall

ADMIN = {"X-Actor-Id": "customer-mcp-admin", "X-Actor-Role": "admin"}
AGENT = {"X-Actor-Id": "customer-mcp-agent", "X-Actor-Role": "agent"}


class FakePlanner:
    def plan_tool(self, **_: object) -> ToolPlan:
        return ToolPlan(
            tool_id="customer-orders.get_order",
            arguments={"order_id": "PDD-2002"},
            reason="订单物流需要实时查询",
        )


class FakeWritePlanner:
    def plan_tool(self, **_: object) -> ToolPlan:
        return ToolPlan(
            tool_id="customer-refunds.refund_order",
            arguments={"order_id": "PDD-3003", "amount": 39.9},
            reason="买家申请退款，需要人工核对退款条件",
        )


def test_reply_suggestion_executes_bound_mcp_tool(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json={
            "employee_key": "customer_mcp_employee",
            "name": "MCP 客服",
            "version": "1.0.0",
            "scenario_type": "customer_service_ticket",
            "workflow_key": "customer_service_ticket_v1",
            "business_unit_id": "bu_demo",
            "service_identity": "digital_employee.customer_mcp",
            "handoff_queue": "MANUAL_TRIAGE",
            "tool_allowlist": ["knowledge.search", "draft.create"],
        },
    )
    assert employee.status_code == 201, employee.text
    connector = client.post(
        "/api/v1/mcp/connectors",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "code": "customer-orders",
            "name": "客户订单中心",
            "url": "http://127.0.0.1:8765/mcp",
            "timeout_seconds": 2,
        },
    )
    assert connector.status_code == 201, connector.text
    with SessionLocal() as session:
        model = session.get(McpConnector, UUID(connector.json()["id"]))
        assert model is not None
        model.tools_json = [
            {
                "name": "get_order",
                "description": "按订单号查询订单和物流状态",
                "input_schema": {
                    "type": "object",
                    "properties": {"order_id": {"type": "string"}},
                    "required": ["order_id"],
                },
                "is_write": False,
            }
        ]
        session.commit()
    binding = client.put(
        (
            "/api/v1/digital-employees/"
            f"{employee.json()['id']}/mcp-connectors"
        ),
        headers=ADMIN,
        json={
            "bindings": [
                {
                    "connector_id": connector.json()["id"],
                    "enabled": True,
                    "allowed_tools": ["get_order"],
                    "write_approved": False,
                }
            ]
        },
    )
    assert binding.status_code == 200, binding.text

    async def fake_remote(
        _runtime: McpToolRuntime,
        connector: McpConnector,
        tool_name: str,
        arguments: dict[str, object],
    ) -> dict[str, Any]:
        assert connector.code == "customer-orders"
        assert tool_name == "get_order"
        assert arguments == {"order_id": "PDD-2002"}
        return {
            "is_error": False,
            "structured_content": {
                "order_id": "PDD-2002",
                "status": "运输中",
                "latest_event": "快件已到达杭州转运中心",
            },
            "content": [],
        }

    monkeypatch.setattr(McpToolRuntime, "_call_remote", fake_remote)
    monkeypatch.setattr(
        suggestion_module,
        "build_tool_planner_for_employee",
        lambda *_args, **_kwargs: FakePlanner(),
    )

    conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "employee_id": employee.json()["id"],
            "requester_ref": "mcp-buyer",
            "category_name": "订单物流",
        },
    )
    assert conversation.status_code == 201, conversation.text
    message = client.post(
        (
            "/api/v1/customer-service/conversations/"
            f"{conversation.json()['id']}/messages"
        ),
        headers=AGENT,
        json={"content": "订单 PDD-2002 到哪了？"},
    )
    assert message.status_code == 202, message.text
    with SessionLocal() as session:
        employee_model = session.get(
            DigitalEmployee,
            UUID(employee.json()["id"]),
        )
        assert employee_model is not None
        assert [
            target.tool_id
            for target in McpToolRuntime(session).available_tools(employee_model)
        ] == ["customer-orders.get_order"]

    suggestion = client.post(
        (
            "/api/v1/customer-service/conversations/"
            f"{conversation.json()['id']}/reply-suggestions"
        ),
        headers=AGENT,
    )
    with SessionLocal() as session:
        calls = list(
            session.scalars(
                select(ToolCall).order_by(ToolCall.started_at)
            ).all()
        )
    assert suggestion.status_code == 200, (
        suggestion.text,
        [
            (call.tool_key, call.status, call.error_message)
            for call in calls
        ],
    )
    payload = suggestion.json()
    assert payload["skill"] == "logistics-inquiry"
    assert payload["citations"][0]["source_type"] == "mcp"
    assert "customer-orders" in payload["citations"][0]["title"]
    assert payload["tool_calls"][0]["tool_id"] == "customer-orders.get_order"
    assert payload["tool_calls"][0]["status"] == "SUCCEEDED"
    assert payload["trace"] == [
        "route_skill → logistics-inquiry · LOGISTICS",
        "retrieve_knowledge → 0 条知识",
        "plan_mcp_tools → customer-orders.get_order",
        "execute_mcp_tool → customer-orders.get_order · SUCCEEDED",
        "generate_reply → local/local-keyword-v1",
    ]


def test_reply_suggestion_opens_approval_without_executing_write(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json={
            "employee_key": "customer_refund_employee",
            "name": "退款审批客服",
            "version": "1.0.0",
            "scenario_type": "customer_service_ticket",
            "workflow_key": "customer_service_ticket_v1",
            "business_unit_id": "bu_demo",
            "service_identity": "digital_employee.customer_refund",
            "handoff_queue": "MANUAL_TRIAGE",
            "tool_allowlist": ["knowledge.search", "draft.create"],
        },
    )
    assert employee.status_code == 201, employee.text
    connector = client.post(
        "/api/v1/mcp/connectors",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "code": "customer-refunds",
            "name": "客户退款中心",
            "url": "http://127.0.0.1:8765/mcp",
            "timeout_seconds": 2,
        },
    )
    assert connector.status_code == 201, connector.text
    with SessionLocal() as session:
        model = session.get(McpConnector, UUID(connector.json()["id"]))
        assert model is not None
        model.tools_json = [
            {
                "name": "refund_order",
                "description": "发起订单退款",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "order_id": {"type": "string"},
                        "amount": {"type": "number"},
                    },
                    "required": ["order_id", "amount"],
                },
                "is_write": True,
            }
        ]
        session.commit()
    binding = client.put(
        (
            "/api/v1/digital-employees/"
            f"{employee.json()['id']}/mcp-connectors"
        ),
        headers=ADMIN,
        json={
            "bindings": [
                {
                    "connector_id": connector.json()["id"],
                    "enabled": True,
                    "allowed_tools": ["refund_order"],
                    "write_approved": True,
                }
            ]
        },
    )
    assert binding.status_code == 200, binding.text

    async def forbidden_remote(
        _runtime: McpToolRuntime,
        _connector: McpConnector,
        _tool_name: str,
        _arguments: dict[str, object],
    ) -> dict[str, Any]:
        raise AssertionError("write tool must not execute during suggestion")

    monkeypatch.setattr(McpToolRuntime, "_call_remote", forbidden_remote)
    monkeypatch.setattr(
        suggestion_module,
        "build_tool_planner_for_employee",
        lambda *_args, **_kwargs: FakeWritePlanner(),
    )

    conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "employee_id": employee.json()["id"],
            "requester_ref": "refund-buyer",
            "category_name": "订单退款",
        },
    )
    assert conversation.status_code == 201, conversation.text
    message = client.post(
        (
            "/api/v1/customer-service/conversations/"
            f"{conversation.json()['id']}/messages"
        ),
        headers=AGENT,
        json={"content": "订单 PDD-3003 申请退款 39.9 元"},
    )
    assert message.status_code == 202, message.text
    with SessionLocal() as session:
        ticket = session.get(
            Ticket,
            UUID(message.json()["current_ticket_id"]),
        )
        assert ticket is not None
        ticket.category_primary = "ecommerce_aftersales"
        ticket.category_secondary = "order_after_sales"
        ticket.risk_level = "R2"
        ticket.priority = "P1"
        ticket.needs_human = True
        session.commit()
        conversation_detail = client.get(
            f"/api/v1/customer-service/conversations/{conversation.json()['id']}",
            headers=AGENT,
        )
        assert conversation_detail.status_code == 200
    takeover = client.post(
        (
            "/api/v1/customer-service/conversations/"
            f"{conversation.json()['id']}/takeover"
        ),
        headers=AGENT,
        json={"expected_version": conversation_detail.json()["version"]},
    )
    assert takeover.status_code == 200, takeover.text

    suggestion = client.post(
        (
            "/api/v1/customer-service/conversations/"
            f"{conversation.json()['id']}/reply-suggestions"
        ),
        headers=AGENT,
    )
    assert suggestion.status_code == 200, suggestion.text
    payload = suggestion.json()
    assert payload["provider"] == "system_policy"
    assert payload["grounding_status"] == "APPROVAL_REQUIRED"
    assert payload["tool_calls"][0]["status"] == "APPROVAL_REQUIRED"
    approval_id = payload["tool_calls"][0]["approval_id"]
    assert approval_id
    assert "审批通过并执行前" in payload["text"]

    with SessionLocal() as session:
        approval = session.get(McpToolApproval, UUID(approval_id))
        assert approval is not None
        assert approval.status == "PENDING"
        assert approval.requested_by in {
            AGENT["X-Actor-Id"],
            "digital_employee.runtime",
        }
        assert approval.arguments_json["amount"] == 39.9

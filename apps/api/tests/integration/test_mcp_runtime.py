from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.mcp_connectors.models import (
    DigitalEmployeeMcpBinding,
    McpConnector,
    McpToolApproval,
)
from ticket_agent.mcp_connectors.runtime import McpToolRuntime
from ticket_agent.shared.db import SessionLocal
from ticket_agent.tickets.models import Ticket
from ticket_agent.tools.models import ToolCall

ADMIN = {"X-Actor-Id": "mcp-runtime-admin", "X-Actor-Role": "admin"}
AGENT = {"X-Actor-Id": "mcp-runtime-agent", "X-Actor-Role": "agent"}
EMPLOYEE_VIEWER = {
    "X-Actor-Id": "mcp-runtime-employee-viewer",
    "X-Actor-Role": "knowledge_operator",
}


def test_mcp_runtime_executes_read_and_blocks_write(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee_response = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json={
            "employee_key": "mcp_runtime_employee",
            "name": "MCP 运行时客服",
            "version": "1.0.0",
            "scenario_type": "customer_service_ticket",
            "workflow_key": "customer_service_ticket_v1",
            "business_unit_id": "bu_demo",
            "service_identity": "digital_employee.mcp_runtime",
            "handoff_queue": "MANUAL_TRIAGE",
            "tool_allowlist": ["knowledge.search", "draft.create"],
        },
    )
    assert employee_response.status_code == 201, employee_response.text
    connector_response = client.post(
        "/api/v1/mcp/connectors",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "code": "runtime-orders",
            "name": "订单运行时",
            "url": "http://127.0.0.1:8765/mcp",
            "timeout_seconds": 2,
        },
    )
    assert connector_response.status_code == 201, connector_response.text
    connector_id = connector_response.json()["id"]

    with SessionLocal() as session:
        connector = session.get(McpConnector, UUID(connector_id))
        assert connector is not None
        connector.tools_json = [
            {
                "name": "get_order",
                "description": "按订单号查询订单状态",
                "input_schema": {
                    "type": "object",
                    "properties": {"order_id": {"type": "string"}},
                    "required": ["order_id"],
                },
                "is_write": False,
            },
            {
                "name": "refund_order",
                "description": "发起退款",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "order_id": {"type": "string"},
                        "amount": {"type": "number"},
                    },
                    "required": ["order_id", "amount"],
                },
                "is_write": True,
            },
            {
                "name": "get_refund_status",
                "description": "查询退款执行状态",
                "input_schema": {
                    "type": "object",
                    "properties": {"order_id": {"type": "string"}},
                    "required": ["order_id"],
                },
                "is_write": False,
            },
            {
                "name": "reverse_refund",
                "description": "冲正退款",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "order_id": {"type": "string"},
                        "amount": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": ["order_id", "amount", "reason"],
                },
                "is_write": True,
            },
        ]
        session.commit()
    bound = client.put(
        (
            "/api/v1/digital-employees/"
            f"{employee_response.json()['id']}/mcp-connectors"
        ),
        headers=ADMIN,
        json={
            "bindings": [
                {
                    "connector_id": connector_id,
                    "enabled": True,
                    "allowed_tools": [
                        "get_order",
                        "refund_order",
                        "get_refund_status",
                        "reverse_refund",
                    ],
                    "write_approved": False,
                }
            ]
        },
    )
    assert bound.status_code == 200, bound.text

    space = client.post(
        "/api/v1/knowledge-spaces",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "code": "mcp_runtime_knowledge",
            "name": "MCP 运行时知识",
            "domain": "customer_service",
            "owner_id": "mcp-runtime-admin",
        },
    )
    assert space.status_code == 201, space.text
    knowledge_bound = client.put(
        (
            "/api/v1/digital-employees/"
            f"{employee_response.json()['id']}/knowledge-bindings"
        ),
        headers=ADMIN,
        json={
            "bindings": [
                {
                    "knowledge_space_id": space.json()["id"],
                    "enabled": True,
                }
            ]
        },
    )
    assert knowledge_bound.status_code == 200, knowledge_bound.text
    available_skills = client.get(
        "/api/v1/skills?business_unit_id=bu_demo",
        headers=AGENT,
    ).json()
    skill_bound = client.put(
        (
            "/api/v1/digital-employees/"
            f"{employee_response.json()['id']}/skills"
        ),
        headers=ADMIN,
        json={
            "bindings": [
                {
                    "skill_id": available_skills[0]["id"],
                    "enabled": True,
                }
            ]
        },
    )
    assert skill_bound.status_code == 200, skill_bound.text
    employees = client.get(
        "/api/v1/digital-employees?business_unit_id=bu_demo",
        headers=EMPLOYEE_VIEWER,
    ).json()
    assert next(
        item
        for item in employees
        if item["id"] == employee_response.json()["id"]
    )["status"] == "ACTIVE"

    captured: list[tuple[str, dict[str, object]]] = []
    fail_next_remote_call = False

    async def fake_remote(
        _runtime: McpToolRuntime,
        connector: McpConnector,
        tool_name: str,
        arguments: dict[str, object],
    ) -> dict[str, Any]:
        assert connector.code == "runtime-orders"
        captured.append((tool_name, arguments))
        if fail_next_remote_call:
            raise TimeoutError("MCP provider timed out")
        if tool_name == "get_refund_status":
            return {
                "is_error": False,
                "structured_content": {
                    "order_id": arguments["order_id"],
                    "refund_status": "NOT_EXECUTED",
                },
                "content": [],
            }
        if tool_name == "reverse_refund":
            return {
                "is_error": False,
                "structured_content": {
                    "order_id": arguments["order_id"],
                    "status": "COMPENSATED",
                },
                "content": [],
            }
        return {
            "is_error": False,
            "structured_content": {
                "order_id": arguments["order_id"],
                "status": "运输中",
                "tracking_number": "SF1234567890",
            },
            "content": [],
        }

    monkeypatch.setattr(McpToolRuntime, "_call_remote", fake_remote)

    with SessionLocal() as session:
        employee = session.get(
            DigitalEmployee,
            UUID(employee_response.json()["id"]),
        )
        assert employee is not None
        ticket = Ticket(
            business_unit_id="bu_demo",
            employee_id=employee.id,
            source_system="mcp-runtime-test",
            source_ticket_id="MCP-RUNTIME-001",
            source_channel="test",
            idempotency_key="mcp-runtime-test-001",
            request_hash="a" * 64,
            requester_ref="mcp-runtime-buyer",
            subject="退款审批测试",
            body="订单商品破损，申请退款。",
            category_primary="ecommerce_aftersales",
            category_secondary="order_after_sales",
            risk_level="R2",
            priority="P1",
            needs_human=True,
        )
        session.add(ticket)
        session.commit()
        ticket_id = ticket.id
        runtime = McpToolRuntime(session)
        assert [
            target.tool_id for target in runtime.available_tools(employee)
        ] == [
            "runtime-orders.get_order",
            "runtime-orders.refund_order",
            "runtime-orders.get_refund_status",
            "runtime-orders.reverse_refund",
        ]

        read_result = runtime.execute(
            employee=employee,
            tool_id="runtime-orders.get_order",
            arguments={"order_id": "PDD-1001"},
            correlation_id="mcp-runtime-read",
            ticket_id=ticket_id,
        )
        assert read_result.status == "SUCCEEDED"
        assert captured == [("get_order", {"order_id": "PDD-1001"})]
        assert read_result.evidence is not None
        assert "运输中" in read_result.evidence.content
        assert read_result.evidence.citation["source_type"] == "mcp"

        invalid_write = runtime.execute(
            employee=employee,
            tool_id="runtime-orders.refund_order",
            arguments={},
            correlation_id="mcp-runtime-invalid-write",
            ticket_id=ticket_id,
            requested_by="requester.agent",
        )
        assert invalid_write.status == "FAILED"
        assert invalid_write.error_code == "MCP_TOOL_ARGUMENTS_INVALID"
        assert invalid_write.approval_id is None
        assert len(captured) == 1

        write_denied = runtime.execute(
            employee=employee,
            tool_id="runtime-orders.refund_order",
            arguments={"order_id": "PDD-1001", "amount": 39.9},
            correlation_id="mcp-runtime-write",
            ticket_id=ticket_id,
        )
        assert write_denied.status == "APPROVAL_REQUIRED"
        assert write_denied.error_code == "MCP_WRITE_PERMISSION_NOT_GRANTED"
        assert len(captured) == 1

        binding = session.scalar(select(DigitalEmployeeMcpBinding))
        assert binding is not None
        binding.write_approved = True
        session.commit()
        write_approval_required = runtime.execute(
            employee=employee,
            tool_id="runtime-orders.refund_order",
            arguments={"order_id": "PDD-1001", "amount": 39.9},
            correlation_id="mcp-runtime-write-approved",
            ticket_id=ticket_id,
            requested_by="requester.agent",
        )
        assert write_approval_required.status == "APPROVAL_REQUIRED"
        assert (
            write_approval_required.error_code
            == "MCP_WRITE_REQUIRES_APPROVAL"
        )
        assert write_approval_required.approval_id is not None
        assert write_approval_required.approval_required_role == "supervisor"
        assert len(captured) == 1

        calls = list(
            session.scalars(
                select(ToolCall).order_by(ToolCall.started_at)
            ).all()
        )
        assert [call.status for call in calls] == [
            "SUCCEEDED",
            "FAILED",
            "DENIED",
            "DENIED",
        ]
        assert calls[0].request_payload["arguments"] == {
            "order_id": "PDD-1001",
        }
        assert calls[1].error_code == "MCP_TOOL_ARGUMENTS_INVALID"
        assert calls[2].error_code == "MCP_WRITE_PERMISSION_NOT_GRANTED"
        assert calls[3].error_code == "MCP_WRITE_REQUIRES_APPROVAL"

        approval_id = str(write_approval_required.approval_id)
        approvals = client.get(
            "/api/v1/mcp/tool-approvals?business_unit_id=bu_demo",
            headers=ADMIN,
        )
        assert approvals.status_code == 200, approvals.text
        assert approvals.json()["items"][0]["id"] == approval_id
        assert approvals.json()["items"][0]["status"] == "PENDING"

        self_approval = client.post(
            f"/api/v1/mcp/tool-approvals/{approval_id}/decisions",
            headers={
                "X-Actor-Id": "requester.agent",
                "X-Actor-Role": "supervisor",
            },
            json={
                "decision": "APPROVE",
                "expected_version": 1,
                "note": "self approval",
            },
        )
        assert self_approval.status_code == 403
        assert (
            self_approval.json()["code"]
            == "MCP_APPROVAL_SELF_APPROVAL_DENIED"
        )

        approved = client.post(
            f"/api/v1/mcp/tool-approvals/{approval_id}/decisions",
            headers={
                "X-Actor-Id": "approval.supervisor",
                "X-Actor-Role": "supervisor",
            },
            json={
                "decision": "APPROVE",
                "expected_version": 1,
                "note": "核对订单和退款金额无误",
            },
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "SUCCEEDED"
        assert approved.json()["decided_by"] == "approval.supervisor"
        assert approved.json()["result"]["text"]
        assert len(captured) == 2

        repeated = client.post(
            f"/api/v1/mcp/tool-approvals/{approval_id}/decisions",
            headers={
                "X-Actor-Id": "approval.supervisor",
                "X-Actor-Role": "supervisor",
            },
            json={
                "decision": "APPROVE",
                "expected_version": 1,
                "note": "retry",
            },
        )
        assert repeated.status_code == 409
        assert len(captured) == 2

        second_request = runtime.execute(
            employee=employee,
            tool_id="runtime-orders.refund_order",
            arguments={"order_id": "13800138000", "amount": 1.0},
            correlation_id="mcp-runtime-write-reject",
            ticket_id=ticket_id,
            requested_by="requester.agent",
        )
        assert second_request.approval_id is not None
        rejected = client.post(
            (
                "/api/v1/mcp/tool-approvals/"
                f"{second_request.approval_id}/decisions"
            ),
            headers={
                "X-Actor-Id": "approval.supervisor",
                "X-Actor-Role": "supervisor",
            },
            json={
                "decision": "REJECT",
                "expected_version": 1,
                "note": "订单不符合退款条件",
            },
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["status"] == "REJECTED"
        assert rejected.json()["arguments"]["order_id"] == "<MOBILE>"
        session.expire_all()
        stored_approval = session.get(McpToolApproval, second_request.approval_id)
        assert stored_approval is not None
        assert stored_approval.execution_arguments_json == {
            "order_id": "13800138000",
            "amount": 1.0,
        }
        assert len(captured) == 2

        fail_next_remote_call = True
        failing_request = runtime.execute(
            employee=employee,
            tool_id="runtime-orders.refund_order",
            arguments={"order_id": "PDD-TIMEOUT", "amount": 99.0},
            correlation_id="mcp-runtime-write-timeout",
            ticket_id=ticket_id,
            requested_by="requester.agent",
        )
        assert failing_request.approval_id is not None
        failing_approval = client.post(
            (
                "/api/v1/mcp/tool-approvals/"
                f"{failing_request.approval_id}/decisions"
            ),
            headers={
                "X-Actor-Id": "approval.supervisor",
                "X-Actor-Role": "supervisor",
            },
            json={
                "decision": "APPROVE",
                "expected_version": 1,
                "note": "执行退款",
            },
        )
        assert failing_approval.status_code == 200, failing_approval.text
        assert failing_approval.json()["status"] == "FAILED"
        assert (
            failing_approval.json()["error_code"] == "MCP_TOOL_CALL_FAILED"
        )

        incidents = client.get(
            "/api/v1/mcp/action-incidents?business_unit_id=bu_demo&status=OPEN",
            headers=ADMIN,
        )
        assert incidents.status_code == 200, incidents.text
        assert incidents.json()["total"] == 1
        incident = incidents.json()["items"][0]
        assert incident["failure_class"] == "EXECUTION_UNKNOWN"
        incident_id = incident["id"]

        fail_next_remote_call = False
        reconciled = client.post(
            f"/api/v1/mcp/action-incidents/{incident_id}/reconcile",
            headers={
                "X-Actor-Id": "incident.supervisor",
                "X-Actor-Role": "supervisor",
            },
            json={"expected_version": 1},
        )
        assert reconciled.status_code == 200, reconciled.text
        assert reconciled.json()["reconciliation_status"] == "SUCCEEDED"
        assert (
            reconciled.json()["reconciliation_tool_id"]
            == "runtime-orders.get_refund_status"
        )
        assert "NOT_EXECUTED" in reconciled.json()["reconciliation_result"]["text"]

        acknowledged = client.post(
            f"/api/v1/mcp/action-incidents/{incident_id}/acknowledge",
            headers={
                "X-Actor-Id": "incident.supervisor",
                "X-Actor-Role": "supervisor",
            },
            json={
                "expected_version": 2,
                "note": "开始核对外部订单和资金状态",
            },
        )
        assert acknowledged.status_code == 200, acknowledged.text
        assert acknowledged.json()["status"] == "ACKNOWLEDGED"

        compensation = client.post(
            f"/api/v1/mcp/action-incidents/{incident_id}/compensation-requests",
            headers={
                "X-Actor-Id": "incident.supervisor",
                "X-Actor-Role": "supervisor",
            },
            json={
                "expected_version": 3,
                "arguments": {
                    "order_id": "PDD-TIMEOUT",
                    "amount": 99.0,
                    "reason": "误执行补偿",
                },
                "note": "外部结果错误，提交管理员补偿审批",
            },
        )
        assert compensation.status_code == 200, compensation.text
        compensation_payload = compensation.json()
        assert compensation_payload["compensation_status"] == "PENDING_APPROVAL"
        compensation_approval_id = compensation_payload["compensation_approval_id"]
        assert compensation_approval_id

        supervisor_compensation = client.post(
            (
                "/api/v1/mcp/tool-approvals/"
                f"{compensation_approval_id}/decisions"
            ),
            headers={
                "X-Actor-Id": "compensation.supervisor",
                "X-Actor-Role": "supervisor",
            },
            json={
                "decision": "APPROVE",
                "expected_version": 1,
                "note": "supervisor should not approve compensation",
            },
        )
        assert supervisor_compensation.status_code == 403
        assert (
            supervisor_compensation.json()["code"]
            == "MCP_APPROVAL_ADMIN_REQUIRED"
        )

        admin_compensation = client.post(
            (
                "/api/v1/mcp/tool-approvals/"
                f"{compensation_approval_id}/decisions"
            ),
            headers={
                "X-Actor-Id": "compensation.admin",
                "X-Actor-Role": "admin",
            },
            json={
                "decision": "APPROVE",
                "expected_version": 1,
                "note": "管理员批准补偿",
            },
        )
        assert admin_compensation.status_code == 200, admin_compensation.text
        assert admin_compensation.json()["status"] == "SUCCEEDED"

        resolved = client.post(
            f"/api/v1/mcp/action-incidents/{incident_id}/resolve",
            headers={
                "X-Actor-Id": "incident.supervisor",
                "X-Actor-Role": "supervisor",
            },
            json={
                "expected_version": 5,
                "note": "订单系统核对后发现错误执行，补偿已完成",
                "outcome": "EXECUTED_INCORRECTLY",
            },
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["status"] == "RESOLVED"
        assert resolved.json()["resolution_outcome"] == "EXECUTED_INCORRECTLY"
        assert resolved.json()["compensation_status"] == "SUCCEEDED"

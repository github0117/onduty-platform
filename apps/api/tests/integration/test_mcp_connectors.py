from fastapi.testclient import TestClient

from ticket_agent.mcp_connectors.service import McpConnectorService

ADMIN = {"X-Actor-Id": "mcp-admin", "X-Actor-Role": "admin"}
AGENT = {"X-Actor-Id": "mcp-agent", "X-Actor-Role": "agent"}


def test_write_name_overrides_read_only_hint() -> None:
    class Tool:
        name = "reverse_refund"
        description = "冲正退款"
        inputSchema = {"type": "object", "properties": {}}
        annotations = type("Annotations", (), {"readOnlyHint": True})()

    view = McpConnectorService._tool_view(Tool())

    assert view.is_write is True


def test_mcp_connector_registration_binding_and_failed_health(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/v1/mcp/connectors",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "code": "order-center",
            "name": "订单中心 MCP",
            "description": "查询订单和物流工具",
            "transport": "streamable_http",
            "url": "http://127.0.0.1:9/mcp",
            "header_env": {"Authorization": "ORDER_MCP_TOKEN"},
            "timeout_seconds": 1,
        },
    )
    assert created.status_code == 201, created.text
    connector_id = created.json()["id"]

    employee = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json={
            "employee_key": "mcp_test_employee",
            "name": "MCP 测试客服",
            "version": "1.0.0",
            "scenario_type": "customer_service_ticket",
            "workflow_key": "customer_service_ticket_v1",
            "business_unit_id": "bu_demo",
            "service_identity": "digital_employee.mcp_test",
            "handoff_queue": "MANUAL_TRIAGE",
            "tool_allowlist": ["ticket.read", "knowledge.search", "draft.create"],
        },
    )
    assert employee.status_code == 201, employee.text
    bound = client.put(
        f"/api/v1/digital-employees/{employee.json()['id']}/mcp-connectors",
        headers=ADMIN,
        json={
            "bindings": [
                {
                    "connector_id": connector_id,
                    "enabled": True,
                    "allowed_tools": ["get_order"],
                    "write_approved": False,
                }
            ]
        },
    )
    assert bound.status_code == 200, bound.text
    assert bound.json()[0]["allowed_tools"] == ["get_order"]
    assert bound.json()[0]["write_approved"] is False

    forbidden_discovery = client.post(
        f"/api/v1/mcp/connectors/{connector_id}/discover",
        headers=AGENT,
    )
    assert forbidden_discovery.status_code == 403

    discovered = client.post(
        f"/api/v1/mcp/connectors/{connector_id}/discover",
        headers=ADMIN,
    )
    assert discovered.status_code == 200
    assert discovered.json()["healthy"] is False
    assert discovered.json()["error"]

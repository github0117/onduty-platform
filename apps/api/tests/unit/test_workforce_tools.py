from types import SimpleNamespace
from uuid import uuid4

import pytest

from ticket_agent.mcp_connectors.runtime import (
    McpExecutionResult,
    McpToolTarget,
)
from ticket_agent.model_gateway.types import ToolPlan
from ticket_agent.workforce import service as workforce_service


def test_workforce_step_uses_only_read_only_mcp_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_target = McpToolTarget(
        connector_id=uuid4(),
        connector_code="orders",
        connector_name="订单中心",
        tool_name="get_logistics",
        description="查询物流",
        input_schema={
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
        is_write=False,
        timeout_seconds=10,
        write_approved=False,
    )
    write_target = McpToolTarget(
        connector_id=read_target.connector_id,
        connector_code="orders",
        connector_name="订单中心",
        tool_name="refund_order",
        description="退款",
        input_schema={"type": "object", "properties": {}},
        is_write=True,
        timeout_seconds=10,
        write_approved=True,
    )
    seen_tool_ids: list[str] = []

    class FakeRuntime:
        def __init__(self, _session: object) -> None:
            pass

        def available_tools(self, _employee: object) -> list[McpToolTarget]:
            return [read_target, write_target]

        def execute(self, **kwargs: object) -> McpExecutionResult:
            assert kwargs["tool_id"] == "orders.get_logistics"
            return McpExecutionResult(
                tool_id="orders.get_logistics",
                connector_code="orders",
                tool_name="get_logistics",
                status="SUCCEEDED",
                text='{"status":"运输中","latest":"杭州转运中心"}',
                error_code=None,
                error_message=None,
                is_write=False,
                duration_ms=18,
                tool_call_id=uuid4(),
            )

    class FakePlanner:
        def plan_tool(self, **kwargs: object) -> ToolPlan:
            tools = kwargs["tools"]
            assert isinstance(tools, list)
            seen_tool_ids.extend(tool.tool_id for tool in tools)
            return ToolPlan(
                tool_id="orders.get_logistics",
                arguments={"order_id": "PDD-1001"},
                reason="需要查询实时物流",
            )

    monkeypatch.setattr(workforce_service, "McpToolRuntime", FakeRuntime)
    monkeypatch.setattr(
        workforce_service,
        "build_tool_planner_for_employee",
        lambda *_args, **_kwargs: FakePlanner(),
    )
    service = workforce_service.WorkforceTaskService(SimpleNamespace())
    snippets, calls = service._execute_read_tools(
        employee=SimpleNamespace(),
        task=SimpleNamespace(
            title="物流处理",
            objective="核实物流停滞",
            context_json={"order_id": "PDD-1001"},
        ),
        step=SimpleNamespace(
            id=uuid4(),
            title="查询专业事实",
            instructions="查询实时物流",
        ),
        skill_instructions="物流必须查询真实接口",
        usage_guard=SimpleNamespace(),
    )

    assert seen_tool_ids == ["orders.get_logistics"]
    assert snippets[0].title.startswith("MCP")
    assert "运输中" in snippets[0].content
    assert calls[0]["status"] == "SUCCEEDED"


def test_workforce_upstream_snippets_include_prior_step_results() -> None:
    completed = SimpleNamespace(
        id=uuid4(),
        sequence=2,
        title="查询专业事实",
        status="SUCCEEDED",
        output_json={
            "summary": "订单在运输中",
            "findings": ["到达杭州转运中心"],
            "recommended_actions": [],
            "citations": [
                {
                    "chunk_id": "mcp:call-1",
                    "source_type": "mcp",
                }
            ],
            "tool_calls": [
                {
                    "tool_id": "orders.get_logistics",
                    "status": "SUCCEEDED",
                }
            ],
        },
    )
    pending = SimpleNamespace(
        id=uuid4(),
        sequence=3,
        title="生成统一处理建议",
        status="PENDING",
        output_json={},
    )

    snippets = workforce_service._upstream_step_snippets(
        [completed, pending],
        before_sequence=3,
    )

    assert len(snippets) == 1
    assert snippets[0].chunk_id == f"workflow-step:{completed.id}"
    assert "订单在运输中" in snippets[0].content
    assert "orders.get_logistics" in snippets[0].content

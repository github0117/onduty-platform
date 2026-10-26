from uuid import uuid4

from ticket_agent.mcp_connectors.policy import evaluate_write_action
from ticket_agent.mcp_connectors.runtime import McpToolTarget
from ticket_agent.tickets.models import Ticket


def _refund_target() -> McpToolTarget:
    return McpToolTarget(
        connector_id=uuid4(),
        connector_code="orders",
        connector_name="订单中心",
        tool_name="refund_order",
        description="发起退款",
        input_schema={
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "amount": {"type": "number"},
            },
            "required": ["order_id", "amount"],
        },
        is_write=True,
        timeout_seconds=20,
        write_approved=True,
    )


def _refund_ticket() -> Ticket:
    return Ticket(
        business_unit_id="bu_demo",
        source_system="policy-test",
        source_ticket_id=f"POLICY-{uuid4()}",
        source_channel="test",
        idempotency_key=f"policy-{uuid4()}",
        request_hash="b" * 64,
        requester_ref="buyer",
        subject="退款",
        body="商品破损申请退款",
        category_primary="ecommerce_aftersales",
        category_secondary="order_after_sales",
        risk_level="R2",
        priority="P1",
        needs_human=True,
    )


def test_refund_policy_assigns_approval_role_and_hard_limit() -> None:
    target = _refund_target()
    ticket = _refund_ticket()

    normal = evaluate_write_action(
        target=target,
        arguments={"order_id": "PDD-1", "amount": 39.9},
        ticket=ticket,
    )
    assert normal.allowed is True
    assert normal.required_role == "supervisor"

    high_value = evaluate_write_action(
        target=target,
        arguments={"order_id": "PDD-1", "amount": 800},
        ticket=ticket,
    )
    assert high_value.allowed is True
    assert high_value.required_role == "admin"

    over_limit = evaluate_write_action(
        target=target,
        arguments={"order_id": "PDD-1", "amount": 6000},
        ticket=ticket,
    )
    assert over_limit.allowed is False
    assert over_limit.reason_code == "MCP_REFUND_ABSOLUTE_LIMIT_EXCEEDED"

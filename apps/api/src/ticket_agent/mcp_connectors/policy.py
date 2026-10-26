from dataclasses import dataclass
from typing import Any

from ticket_agent.mcp_connectors.runtime import McpToolTarget
from ticket_agent.shared.settings import get_settings
from ticket_agent.tickets.domain import RiskLevel
from ticket_agent.tickets.models import Ticket


@dataclass(frozen=True)
class McpActionPolicyResult:
    allowed: bool
    reason_code: str
    reason: str
    required_role: str
    facts: dict[str, Any]

    @property
    def snapshot(self) -> dict[str, Any]:
        return {
            "reason_code": self.reason_code,
            "reason": self.reason,
            "required_role": self.required_role,
            "facts": self.facts,
        }


def evaluate_write_action(
    *,
    target: McpToolTarget,
    arguments: dict[str, object],
    ticket: Ticket | None,
) -> McpActionPolicyResult:
    settings = get_settings()
    if not target.is_write:
        return McpActionPolicyResult(
            allowed=True,
            reason_code="READ_ONLY",
            reason="Read-only MCP action.",
            required_role="none",
            facts={},
        )
    if ticket is None:
        return McpActionPolicyResult(
            allowed=False,
            reason_code="MCP_ACTION_TICKET_REQUIRED",
            reason="Write actions require an associated support ticket.",
            required_role="admin",
            facts={"tool_id": target.tool_id},
        )

    tool_name = target.tool_name.lower()
    risk_level = ticket.risk_level or ""
    category = ticket.category_primary or ""
    is_after_sales = category == "ecommerce_aftersales"
    is_high_risk = risk_level in {RiskLevel.R2.value, RiskLevel.R3.value}
    if not is_after_sales and not is_high_risk:
        return McpActionPolicyResult(
            allowed=False,
            reason_code="MCP_ACTION_CONTEXT_MISMATCH",
            reason=(
                "Write action requires an after-sales ticket or R2/R3 risk."
            ),
            required_role="admin",
            facts={
                "category": category,
                "risk_level": risk_level,
                "tool_id": target.tool_id,
            },
        )

    if "reverse" in tool_name or "compensat" in tool_name:
        return McpActionPolicyResult(
            allowed=True,
            reason_code="COMPENSATION_POLICY_PASSED",
            reason="Compensation action requires administrator approval.",
            required_role="admin",
            facts={
                "category": category,
                "risk_level": risk_level,
                "tool_id": target.tool_id,
            },
        )

    if "refund" in tool_name:
        raw_amount = arguments.get("amount")
        if isinstance(raw_amount, bool) or not isinstance(raw_amount, (int, float)):
            return McpActionPolicyResult(
                allowed=False,
                reason_code="MCP_REFUND_AMOUNT_INVALID",
                reason="Refund amount must be a positive number.",
                required_role="admin",
                facts={"amount": raw_amount},
            )
        amount = float(raw_amount)
        if amount <= 0:
            return McpActionPolicyResult(
                allowed=False,
                reason_code="MCP_REFUND_AMOUNT_INVALID",
                reason="Refund amount must be greater than zero.",
                required_role="admin",
                facts={"amount": amount},
            )
        if amount > settings.mcp_refund_absolute_limit:
            return McpActionPolicyResult(
                allowed=False,
                reason_code="MCP_REFUND_ABSOLUTE_LIMIT_EXCEEDED",
                reason="Refund exceeds the platform's hard limit.",
                required_role="admin",
                facts={
                    "amount": amount,
                    "absolute_limit": settings.mcp_refund_absolute_limit,
                },
            )
        required_role = (
            "admin"
            if amount > settings.mcp_refund_supervisor_limit
            else "supervisor"
        )
        return McpActionPolicyResult(
            allowed=True,
            reason_code="REFUND_POLICY_PASSED",
            reason=(
                "Refund action passed deterministic amount and ticket checks."
            ),
            required_role=required_role,
            facts={
                "amount": amount,
                "supervisor_limit": settings.mcp_refund_supervisor_limit,
                "absolute_limit": settings.mcp_refund_absolute_limit,
                "category": category,
                "risk_level": risk_level,
            },
        )

    return McpActionPolicyResult(
        allowed=True,
        reason_code="GENERIC_WRITE_POLICY_PASSED",
        reason="Generic write action requires independent supervisor approval.",
        required_role="supervisor",
        facts={
            "category": category,
            "risk_level": risk_level,
            "tool_id": target.tool_id,
        },
    )

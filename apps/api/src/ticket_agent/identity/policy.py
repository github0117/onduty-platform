"""Single source of truth for role-based capabilities.

Every backend guard and the ``GET /api/v1/me`` response read from this module.
The frontend must not keep its own role -> capability table.
"""

from ticket_agent.identity.models import Principal
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import get_settings

POLICY_VERSION = "2026-10-27"

CAPABILITIES: tuple[str, ...] = (
    "platform.overview",
    "tickets.view_self",
    "tickets.view",
    "tickets.write",
    "tickets.sync",
    "service.chat",
    "service.workbench",
    "service.admin",
    "service.approvals.view",
    "service.approvals.decide",
    "service.incidents.view",
    "service.incidents.manage",
    "knowledge.view",
    "knowledge.use",
    "knowledge.write",
    "employees.directory",
    "employees.view",
    "employees.write",
    "ecommerce.view",
    "ecommerce.operate",
    "ecommerce.catalog.write",
    "operations.view",
    "operations.manage",
    "mcp.connectors.view",
    "mcp.connectors.write",
    "models.view",
    "demo.reset",
)

ALL_CAPABILITIES = frozenset(CAPABILITIES)

ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    "requester": frozenset({"tickets.view_self"}),
    "agent": frozenset(
        {
            "tickets.view",
            "tickets.write",
            "service.chat",
            "service.workbench",
            "knowledge.view",
            "knowledge.use",
            "employees.directory",
            "ecommerce.view",
        }
    ),
    "supervisor": frozenset(
        {
            "tickets.view",
            "tickets.write",
            "tickets.sync",
            "service.chat",
            "service.workbench",
            "service.admin",
            "service.approvals.view",
            "service.approvals.decide",
            "service.incidents.view",
            "service.incidents.manage",
            "knowledge.view",
            "knowledge.use",
            "employees.directory",
            "ecommerce.view",
            "ecommerce.operate",
            "operations.view",
            "operations.manage",
            "mcp.connectors.view",
        }
    ),
    "knowledge_operator": frozenset(
        {
            "knowledge.view",
            "knowledge.use",
            "knowledge.write",
            "employees.directory",
            "employees.view",
            "employees.write",
            "ecommerce.view",
            "ecommerce.catalog.write",
            "operations.view",
            "mcp.connectors.view",
            "mcp.connectors.write",
        }
    ),
    "business_manager": frozenset(
        {
            "tickets.view",
            "service.approvals.view",
            "service.incidents.view",
            "knowledge.view",
            "knowledge.use",
            "ecommerce.view",
            "operations.view",
            "mcp.connectors.view",
        }
    ),
    "auditor": frozenset(
        {
            "tickets.view",
            "service.approvals.view",
            "service.incidents.view",
            "knowledge.view",
            "knowledge.use",
            "operations.view",
            "mcp.connectors.view",
        }
    ),
    "admin": ALL_CAPABILITIES,
}

ROLE_LABELS: dict[str, str] = {
    "requester": "需求方",
    "agent": "客服坐席",
    "supervisor": "客服主管",
    "knowledge_operator": "知识运营",
    "business_manager": "业务经理",
    "auditor": "审计员",
    "admin": "平台管理员",
}

DEMO_RESET_BUSINESS_UNIT = "bu_demo"
DEMO_RESET_BUSINESS_UNIT_LABELS: dict[str, str] = {
    "bu_demo": "演示租户（固定数据）",
    "bu_acceptance": "隔离验真租户（无演示数据）",
}


def capabilities_for(role: str) -> frozenset[str]:
    """Return the capabilities for a normalized role.

    Unknown roles are treated as ``requester`` because ``normalize_role``
    already maps unknown OIDC roles there. This keeps a bad role from ever
    acquiring administrator capabilities.
    """

    return ROLE_CAPABILITIES.get(role, ROLE_CAPABILITIES["requester"])


def has_capability(principal: Principal, capability: str) -> bool:
    return capability in capabilities_for(principal.role)


def require_capability(
    principal: Principal,
    capability: str,
    *,
    code: str = "FORBIDDEN",
    title: str = "Operation not permitted",
    detail: str | None = None,
) -> None:
    if has_capability(principal, capability):
        return
    raise ApiProblem(
        status_code=403,
        code=code,
        title=title,
        detail=detail or f"This operation requires the {capability} capability.",
    )


def demo_reset_feature(
    principal: Principal,
    active_business_unit_id: str,
) -> dict[str, object]:
    """Return the reset feature snapshot used by ``/me``.

    The endpoint still performs the authoritative checks; this snapshot only
    tells the UI whether it is worth rendering the reset action.
    """

    settings = get_settings()
    enabled = True
    reason: str | None = None
    if not has_capability(principal, "demo.reset"):
        enabled = False
        reason = "role_not_permitted"
    elif not settings.demo_reset_enabled:
        enabled = False
        reason = "disabled_by_settings"
    elif settings.app_env not in {"development", "test"}:
        enabled = False
        reason = "environment_not_allowed"
    elif active_business_unit_id != DEMO_RESET_BUSINESS_UNIT:
        enabled = False
        reason = "active_business_unit_not_demo"

    return {
        "enabled": enabled,
        "business_unit_id": DEMO_RESET_BUSINESS_UNIT,
        "active_business_unit_eligible": (
            active_business_unit_id == DEMO_RESET_BUSINESS_UNIT
        ),
        "reason": reason,
    }

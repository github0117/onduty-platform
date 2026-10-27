import pytest

from ticket_agent.identity.dependencies import (
    ensure_approvals_viewer,
    ensure_ecommerce_catalog_admin,
    ensure_ecommerce_operator,
    ensure_ecommerce_viewer,
    ensure_employee_console_viewer,
    ensure_employee_directory_viewer,
    ensure_employee_writer,
    ensure_knowledge_admin,
    ensure_mcp_approver,
    ensure_metrics_viewer,
    ensure_service_admin,
    ensure_service_chat,
    ensure_service_workbench,
    ensure_sync_batch_operator,
    ensure_ticket_sync,
    ensure_ticket_writer,
)
from ticket_agent.identity.models import Principal
from ticket_agent.identity.policy import (
    ALL_CAPABILITIES,
    CAPABILITIES,
    ROLE_CAPABILITIES,
    capabilities_for,
    has_capability,
)
from ticket_agent.shared.errors import ApiProblem

ROLES = (
    "requester",
    "agent",
    "supervisor",
    "knowledge_operator",
    "business_manager",
    "auditor",
    "admin",
)


def _principal(role: str) -> Principal:
    return Principal(
        actor_id=f"{role}-1",
        role=role,
        service_identity="digital_agent.ticket.v1",
        business_units=("bu_demo",),
    )


def test_every_role_capability_is_declared() -> None:
    for role, capabilities in ROLE_CAPABILITIES.items():
        assert capabilities <= ALL_CAPABILITIES, role


def test_role_matrix_key_contracts() -> None:
    assert capabilities_for("requester") == frozenset({"tickets.view_self"})

    agent = capabilities_for("agent")
    assert {"tickets.view", "tickets.write", "service.chat"} <= agent
    assert "service.admin" not in agent
    assert "operations.view" not in agent
    assert "ecommerce.view" in agent
    assert "ecommerce.operate" not in agent
    assert "knowledge.write" not in agent
    assert "employees.directory" in agent
    assert "employees.view" not in agent
    assert "employees.write" not in agent

    supervisor = capabilities_for("supervisor")
    assert {
        "tickets.sync",
        "service.admin",
        "service.approvals.view",
        "service.approvals.decide",
        "ecommerce.operate",
        "operations.manage",
    } <= supervisor
    assert "knowledge.write" not in supervisor
    assert "demo.reset" not in supervisor

    knowledge_operator = capabilities_for("knowledge_operator")
    assert {
        "knowledge.write",
        "employees.directory",
        "employees.view",
        "employees.write",
        "ecommerce.catalog.write",
        "operations.view",
    } <= knowledge_operator
    assert "tickets.write" not in knowledge_operator
    assert "ecommerce.operate" not in knowledge_operator
    assert "operations.manage" not in knowledge_operator

    for read_only_role in ("business_manager", "auditor"):
        capabilities = capabilities_for(read_only_role)
        assert {
            "tickets.view",
            "service.approvals.view",
            "service.incidents.view",
            "operations.view",
        } <= capabilities
        assert "employees.directory" not in capabilities
        assert "employees.view" not in capabilities
        assert "tickets.write" not in capabilities
        assert "service.approvals.decide" not in capabilities
        assert "service.incidents.manage" not in capabilities
        assert "ecommerce.operate" not in capabilities
        assert "operations.manage" not in capabilities


def test_admin_holds_every_declared_capability() -> None:
    assert capabilities_for("admin") == ALL_CAPABILITIES
    assert set(CAPABILITIES) == ALL_CAPABILITIES


def test_unknown_role_falls_back_to_requester() -> None:
    assert capabilities_for("unexpected_role") == capabilities_for("requester")
    assert not has_capability(_principal("unexpected_role"), "tickets.write")


@pytest.mark.parametrize(
    ("guard", "role", "allowed"),
    [
        (ensure_ticket_writer, "agent", True),
        (ensure_ticket_writer, "auditor", False),
        (ensure_ticket_sync, "supervisor", True),
        (ensure_ticket_sync, "agent", False),
        (ensure_service_chat, "agent", True),
        (ensure_service_chat, "business_manager", False),
        (ensure_service_workbench, "agent", True),
        (ensure_service_workbench, "auditor", False),
        (ensure_service_admin, "supervisor", True),
        (ensure_service_admin, "agent", False),
        (ensure_ecommerce_viewer, "agent", True),
        (ensure_ecommerce_viewer, "requester", False),
        (ensure_ecommerce_operator, "supervisor", True),
        (ensure_ecommerce_operator, "agent", False),
        (ensure_ecommerce_catalog_admin, "knowledge_operator", True),
        (ensure_ecommerce_catalog_admin, "supervisor", False),
        (ensure_knowledge_admin, "knowledge_operator", True),
        (ensure_knowledge_admin, "agent", False),
        (ensure_metrics_viewer, "auditor", True),
        (ensure_metrics_viewer, "agent", False),
        (ensure_sync_batch_operator, "supervisor", True),
        (ensure_sync_batch_operator, "business_manager", False),
        (ensure_approvals_viewer, "business_manager", True),
        (ensure_approvals_viewer, "agent", False),
        (ensure_employee_directory_viewer, "knowledge_operator", True),
        (ensure_employee_directory_viewer, "agent", True),
        (ensure_employee_directory_viewer, "supervisor", True),
        (ensure_employee_directory_viewer, "business_manager", False),
        (ensure_employee_console_viewer, "knowledge_operator", True),
        (ensure_employee_console_viewer, "supervisor", False),
        (ensure_employee_console_viewer, "agent", False),
        (ensure_employee_writer, "knowledge_operator", True),
        (ensure_employee_writer, "supervisor", False),
        (ensure_mcp_approver, "supervisor", True),
        (ensure_mcp_approver, "auditor", False),
    ],
)
def test_guard_capability_contract(guard, role: str, allowed: bool) -> None:
    principal = _principal(role)
    if allowed:
        guard(principal)
        return
    with pytest.raises(ApiProblem) as exc:
        guard(principal)
    assert exc.value.status_code == 403
    assert exc.value.code in {"FORBIDDEN", "MCP_APPROVAL_ROLE_REQUIRED"}


def test_mcp_approver_keeps_its_error_code() -> None:
    with pytest.raises(ApiProblem) as exc:
        ensure_mcp_approver(_principal("auditor"))
    assert exc.value.code == "MCP_APPROVAL_ROLE_REQUIRED"

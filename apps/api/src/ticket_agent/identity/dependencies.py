from typing import Annotated

from fastapi import Depends, Header, Request

from ticket_agent.identity.models import Principal
from ticket_agent.identity.oidc import get_oidc_authenticator, normalize_role
from ticket_agent.identity.policy import has_capability, require_capability
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import get_settings


def get_principal(
    authorization: str | None = Header(default=None),
    x_actor_id: str | None = Header(default=None),
    x_actor_role: str = Header(default="agent"),
    x_business_unit_id: str | None = Header(default=None),
    x_business_units: str | None = Header(default=None),
) -> Principal:
    settings = get_settings()
    if settings.app_auth_mode == "oidc":
        if not authorization:
            raise ApiProblem(
                status_code=401,
                code="UNAUTHENTICATED",
                title="Authentication required",
                detail="A Bearer token is required.",
            )
        scheme, separator, token = authorization.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token.strip():
            raise ApiProblem(
                status_code=401,
                code="UNAUTHENTICATED",
                title="Authentication failed",
                detail="Authorization must use the Bearer scheme.",
            )
        return get_oidc_authenticator().authenticate(token.strip())

    actor_id = x_actor_id or "demo.agent"
    business_units = _business_units_from_header(
        x_business_unit_id,
        x_business_units,
    )
    return Principal(
        actor_id=actor_id,
        role=normalize_role(x_actor_role),
        service_identity="digital_agent.ticket.v1",
        customer_ref=actor_id,
        business_units=business_units,
    )


def ensure_business_unit_access(
    principal: Principal,
    business_unit_id: str,
) -> None:
    if business_unit_id not in principal.business_units:
        raise ApiProblem(
            status_code=403,
            code="BUSINESS_UNIT_ACCESS_DENIED",
            title="Business unit access denied",
            detail="The actor is not authorized for this business unit.",
        )


def resolve_business_unit(
    principal: Principal,
    requested: str | None = None,
) -> str:
    business_unit_id = requested or principal.primary_business_unit_id
    if business_unit_id is None:
        raise ApiProblem(
            status_code=403,
            code="BUSINESS_UNIT_CONTEXT_REQUIRED",
            title="Business unit context required",
            detail="The identity has no authorized business unit.",
        )
    ensure_business_unit_access(principal, business_unit_id)
    return business_unit_id


def tenant_query_guard(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> None:
    requested = request.query_params.get("business_unit_id")
    if requested:
        ensure_business_unit_access(principal, requested)


def _business_units_from_header(
    primary: str | None,
    all_units: str | None,
) -> tuple[str, ...]:
    values: list[str] = []
    if all_units:
        values.extend(all_units.split(","))
    if primary:
        values.insert(0, primary)
    normalized = tuple(
        dict.fromkeys(
            value.strip()
            for value in values
            if value.strip()
        )
    )
    return normalized or ("bu_demo",)


def ensure_ticket_writer(principal: Principal) -> None:
    require_capability(
        principal,
        "tickets.write",
        detail="This operation requires a support agent or supervisor role.",
    )


def ensure_ticket_sync(principal: Principal) -> None:
    require_capability(
        principal,
        "tickets.sync",
        title="Batch sync operation denied",
        detail="Batch sync retry requires a supervisor or administrator role.",
    )


def ensure_workspace_viewer(principal: Principal) -> None:
    require_capability(
        principal,
        "knowledge.view",
        title="Workspace access denied",
        detail="This operation requires a workspace viewer role.",
    )


def ensure_ticket_creator(principal: Principal, requester_ref: str) -> None:
    if has_capability(principal, "tickets.write"):
        return
    if principal.role != "requester":
        raise ApiProblem(
            status_code=403,
            code="FORBIDDEN",
            title="Ticket creation denied",
            detail="This identity role cannot create tickets.",
        )
    if principal.customer_ref != requester_ref:
        raise ApiProblem(
            status_code=403,
            code="FORBIDDEN",
            title="Ticket creation denied",
            detail="A requester may only create tickets for their own customer reference.",
        )


def ensure_ticket_view(principal: Principal, requester_ref: str) -> None:
    if has_capability(principal, "tickets.view"):
        return
    if principal.customer_ref != requester_ref:
        raise ApiProblem(
            status_code=403,
            code="FORBIDDEN",
            title="Ticket access denied",
            detail="A requester may only view their own tickets.",
        )


def ensure_knowledge_admin(principal: Principal) -> None:
    require_capability(
        principal,
        "knowledge.write",
        title="Knowledge operation denied",
        detail="Knowledge publishing requires an administrator role.",
    )


def ensure_knowledge_worker(principal: Principal) -> None:
    require_capability(
        principal,
        "knowledge.use",
        title="Knowledge operation denied",
        detail="This operation requires a knowledge operator or support role.",
    )


def ensure_metrics_viewer(principal: Principal) -> None:
    require_capability(
        principal,
        "operations.view",
        title="Metrics access denied",
        detail="Metrics require a supervisor, administrator or auditor role.",
    )


def ensure_sync_batch_operator(principal: Principal) -> None:
    require_capability(
        principal,
        "operations.manage",
        title="Batch sync operation denied",
        detail="Batch sync retry requires a supervisor or administrator role.",
    )


def ensure_service_chat(principal: Principal) -> None:
    require_capability(
        principal,
        "service.chat",
        title="Customer service access denied",
        detail="This operation requires a customer service role.",
    )


def ensure_service_workbench(principal: Principal) -> None:
    require_capability(
        principal,
        "service.workbench",
        title="Workbench access denied",
        detail="This operation requires a human service workbench role.",
    )


def ensure_service_admin(principal: Principal) -> None:
    require_capability(
        principal,
        "service.admin",
        title="Service console access denied",
        detail="This operation requires a supervisor or administrator role.",
    )


def ensure_ecommerce_viewer(principal: Principal) -> None:
    require_capability(
        principal,
        "ecommerce.view",
        title="E-commerce access denied",
        detail="This operation requires read access to e-commerce resources.",
    )


def ensure_ecommerce_operator(principal: Principal) -> None:
    require_capability(
        principal,
        "ecommerce.operate",
        title="E-commerce operation denied",
        detail="This operation requires a supervisor or administrator role.",
    )


def ensure_ecommerce_catalog_admin(principal: Principal) -> None:
    require_capability(
        principal,
        "ecommerce.catalog.write",
        title="E-commerce catalog operation denied",
        detail="Catalog maintenance requires a knowledge operator or administrator.",
    )


def ensure_employee_directory_viewer(principal: Principal) -> None:
    require_capability(
        principal,
        "employees.directory",
        title="Employee access denied",
        detail=(
            "This operation requires a support, supervisor, knowledge operator "
            "or administrator role."
        ),
    )


def ensure_employee_console_viewer(principal: Principal) -> None:
    require_capability(
        principal,
        "employees.view",
        title="Employee console access denied",
        detail=(
            "Employee templates, drafts and routing configuration require a "
            "knowledge operator or administrator role."
        ),
    )


def ensure_employee_writer(principal: Principal) -> None:
    require_capability(
        principal,
        "employees.write",
        title="Employee operation denied",
        detail="Employee configuration requires a knowledge operator or administrator role.",
    )


def ensure_approvals_viewer(principal: Principal) -> None:
    require_capability(
        principal,
        "service.approvals.view",
        title="Approval access denied",
        detail="This operation requires a supervisor, business manager or auditor role.",
    )


def ensure_mcp_approver(principal: Principal) -> None:
    require_capability(
        principal,
        "service.approvals.decide",
        code="MCP_APPROVAL_ROLE_REQUIRED",
        title="Supervisor approval required",
        detail="MCP write approvals require a supervisor or administrator.",
    )


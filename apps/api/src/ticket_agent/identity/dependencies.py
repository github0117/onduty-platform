from typing import Annotated

from fastapi import Depends, Header, Request

from ticket_agent.identity.models import Principal
from ticket_agent.identity.oidc import get_oidc_authenticator, normalize_role
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
    if principal.role not in {"agent", "supervisor", "admin"}:
        raise ApiProblem(
            status_code=403,
            code="FORBIDDEN",
            title="Operation not permitted",
            detail="This operation requires a support agent or supervisor role.",
        )


def ensure_workspace_viewer(principal: Principal) -> None:
    if principal.role not in {
        "agent",
        "supervisor",
        "knowledge_operator",
        "business_manager",
        "admin",
        "auditor",
    }:
        raise ApiProblem(
            status_code=403,
            code="FORBIDDEN",
            title="Workspace access denied",
            detail="This operation requires a workspace viewer role.",
        )


def ensure_ticket_creator(principal: Principal, requester_ref: str) -> None:
    if principal.role in {"agent", "supervisor", "admin"}:
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
    if principal.role in {
        "agent",
        "supervisor",
        "business_manager",
        "admin",
        "auditor",
    }:
        return
    if principal.customer_ref != requester_ref:
        raise ApiProblem(
            status_code=403,
            code="FORBIDDEN",
            title="Ticket access denied",
            detail="A requester may only view their own tickets.",
        )


def ensure_knowledge_admin(principal: Principal) -> None:
    if principal.role not in {"admin", "knowledge_operator"}:
        raise ApiProblem(
            status_code=403,
            code="FORBIDDEN",
            title="Knowledge operation denied",
            detail="Knowledge publishing requires an administrator role.",
        )


def ensure_knowledge_worker(principal: Principal) -> None:
    if principal.role not in {
        "agent",
        "supervisor",
        "knowledge_operator",
        "admin",
    }:
        raise ApiProblem(
            status_code=403,
            code="FORBIDDEN",
            title="Knowledge operation denied",
            detail="This operation requires a knowledge operator or support role.",
        )


def ensure_metrics_viewer(principal: Principal) -> None:
    if principal.role not in {
        "supervisor",
        "knowledge_operator",
        "business_manager",
        "admin",
        "auditor",
    }:
        raise ApiProblem(
            status_code=403,
            code="FORBIDDEN",
            title="Metrics access denied",
            detail="Metrics require a supervisor, administrator or auditor role.",
        )


def ensure_sync_batch_operator(principal: Principal) -> None:
    if principal.role not in {"supervisor", "admin"}:
        raise ApiProblem(
            status_code=403,
            code="FORBIDDEN",
            title="Batch sync operation denied",
            detail="Batch sync retry requires a supervisor or administrator role.",
        )


def ensure_mcp_approver(principal: Principal) -> None:
    if principal.role not in {"supervisor", "admin"}:
        raise ApiProblem(
            status_code=403,
            code="MCP_APPROVAL_ROLE_REQUIRED",
            title="Supervisor approval required",
            detail="MCP write approvals require a supervisor or administrator.",
        )


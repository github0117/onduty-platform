from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from ticket_agent.api.dependencies import Actor, DbSession, correlation_id
from ticket_agent.audit.service import record_audit
from ticket_agent.digital_employees.service import DigitalEmployeeService
from ticket_agent.identity.dependencies import (
    ensure_business_unit_access,
    ensure_knowledge_admin,
    ensure_mcp_approver,
    ensure_ticket_writer,
    resolve_business_unit,
)
from ticket_agent.mcp_connectors.approvals import McpToolApprovalService
from ticket_agent.mcp_connectors.incidents import McpActionIncidentService
from ticket_agent.mcp_connectors.schemas import (
    EmployeeMcpBindingReplace,
    EmployeeMcpBindingView,
    McpActionIncidentAction,
    McpActionIncidentCompensation,
    McpActionIncidentList,
    McpActionIncidentReconcile,
    McpActionIncidentResolve,
    McpActionIncidentView,
    McpConnectorCreate,
    McpConnectorUpdate,
    McpConnectorView,
    McpHealthView,
    McpToolApprovalDecision,
    McpToolApprovalList,
    McpToolApprovalView,
)
from ticket_agent.mcp_connectors.service import McpConnectorService
from ticket_agent.shared.rate_limit import rate_limited

router = APIRouter()


@router.get("/mcp/connectors", response_model=list[McpConnectorView])
def list_mcp_connectors(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> list[McpConnectorView]:
    ensure_ticket_writer(principal)
    business_unit_id = resolve_business_unit(
        principal,
        business_unit_id,
    )
    service = McpConnectorService(db)
    return [
        service.view(connector)
        for connector in service.list_connectors(business_unit_id)
    ]


@router.post(
    "/mcp/connectors",
    response_model=McpConnectorView,
    status_code=status.HTTP_201_CREATED,
)
def create_mcp_connector(
    payload: McpConnectorCreate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> McpConnectorView:
    ensure_knowledge_admin(principal)
    ensure_business_unit_access(principal, payload.business_unit_id)
    service = McpConnectorService(db)
    connector = service.create(payload, actor_id=principal.actor_id)
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="mcp_connector.created",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="mcp_connector",
        resource_id=connector.id,
        action="create",
        decision="EXECUTED",
        payload={"code": connector.code, "transport": connector.transport},
    )
    db.commit()
    return service.view(connector)


@router.patch("/mcp/connectors/{connector_id}", response_model=McpConnectorView)
def update_mcp_connector(
    connector_id: UUID,
    payload: McpConnectorUpdate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> McpConnectorView:
    ensure_knowledge_admin(principal)
    service = McpConnectorService(db)
    ensure_business_unit_access(
        principal,
        service.get(connector_id).business_unit_id,
    )
    connector = service.update(
        connector_id,
        payload,
        actor_id=principal.actor_id,
    )
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="mcp_connector.updated",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="mcp_connector",
        resource_id=connector.id,
        action="update",
        decision="EXECUTED",
        payload=payload.model_dump(mode="json", exclude_none=True),
    )
    db.commit()
    return service.view(connector)


@router.post("/mcp/connectors/{connector_id}/discover", response_model=McpHealthView)
async def discover_mcp_connector(
    connector_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> McpHealthView:
    ensure_knowledge_admin(principal)
    service = McpConnectorService(db)
    ensure_business_unit_access(
        principal,
        service.get(connector_id).business_unit_id,
    )
    result = await service.discover(
        connector_id,
        actor_id=principal.actor_id,
    )
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="mcp_connector.discovered",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="mcp_connector",
        resource_id=connector_id,
        action="discover",
        decision="EXECUTED" if result.healthy else "FAILED",
        payload={
            "healthy": result.healthy,
            "tool_count": result.tool_count,
            "error": result.error,
        },
    )
    db.commit()
    return result


@router.get(
    "/digital-employees/{employee_id}/mcp-connectors",
    response_model=list[EmployeeMcpBindingView],
)
def list_employee_mcp_connectors(
    employee_id: UUID,
    db: DbSession,
    principal: Actor,
) -> list[EmployeeMcpBindingView]:
    ensure_ticket_writer(principal)
    ensure_business_unit_access(
        principal,
        DigitalEmployeeService(db).get(employee_id).business_unit_id,
    )
    return McpConnectorService(db).list_employee_bindings(employee_id)


@router.put(
    "/digital-employees/{employee_id}/mcp-connectors",
    response_model=list[EmployeeMcpBindingView],
)
def replace_employee_mcp_connectors(
    employee_id: UUID,
    payload: EmployeeMcpBindingReplace,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> list[EmployeeMcpBindingView]:
    ensure_knowledge_admin(principal)
    ensure_business_unit_access(
        principal,
        DigitalEmployeeService(db).get(employee_id).business_unit_id,
    )
    service = McpConnectorService(db)
    bindings = service.replace_employee_bindings(
        employee_id,
        [binding.model_dump() for binding in payload.bindings],
        actor_id=principal.actor_id,
    )
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="digital_employee.mcp_connectors.updated",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="digital_employee",
        resource_id=employee_id,
        action="replace_mcp_connectors",
        decision="EXECUTED",
        payload={"binding_count": len(bindings)},
    )
    db.commit()
    return bindings


@router.get("/mcp/tool-approvals", response_model=McpToolApprovalList)
def list_mcp_tool_approvals(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
    approval_status: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> McpToolApprovalList:
    ensure_ticket_writer(principal)
    business_unit_id = resolve_business_unit(
        principal,
        business_unit_id,
    )
    return McpToolApprovalService(db).list(
        business_unit_id=business_unit_id,
        status=approval_status,
        limit=limit,
    )


@router.post(
    "/mcp/tool-approvals/{approval_id}/decisions",
    response_model=McpToolApprovalView,
    dependencies=[Depends(rate_limited())],
)
def decide_mcp_tool_approval(
    approval_id: UUID,
    payload: McpToolApprovalDecision,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> McpToolApprovalView:
    ensure_mcp_approver(principal)
    service = McpToolApprovalService(db)
    ensure_business_unit_access(
        principal,
        service.get(approval_id).business_unit_id,
    )
    return service.decide(
        approval_id,
        payload,
        actor_id=principal.actor_id,
        actor_role=principal.role,
        correlation_id=correlation_id(request),
    )


@router.get(
    "/mcp/action-incidents",
    response_model=McpActionIncidentList,
)
def list_mcp_action_incidents(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
    incident_status: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> McpActionIncidentList:
    ensure_ticket_writer(principal)
    business_unit_id = resolve_business_unit(
        principal,
        business_unit_id,
    )
    return McpActionIncidentService(db).list(
        business_unit_id=business_unit_id,
        status=incident_status,
        limit=limit,
    )


@router.post(
    "/mcp/action-incidents/{incident_id}/acknowledge",
    response_model=McpActionIncidentView,
)
def acknowledge_mcp_action_incident(
    incident_id: UUID,
    payload: McpActionIncidentAction,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> McpActionIncidentView:
    ensure_mcp_approver(principal)
    service = McpActionIncidentService(db)
    ensure_business_unit_access(
        principal,
        service.get(incident_id).business_unit_id,
    )
    return service.acknowledge(
        incident_id,
        payload,
        actor_id=principal.actor_id,
        correlation_id=correlation_id(request),
    )


@router.post(
    "/mcp/action-incidents/{incident_id}/resolve",
    response_model=McpActionIncidentView,
)
def resolve_mcp_action_incident(
    incident_id: UUID,
    payload: McpActionIncidentResolve,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> McpActionIncidentView:
    ensure_mcp_approver(principal)
    service = McpActionIncidentService(db)
    ensure_business_unit_access(
        principal,
        service.get(incident_id).business_unit_id,
    )
    return service.resolve(
        incident_id,
        payload,
        actor_id=principal.actor_id,
        correlation_id=correlation_id(request),
    )


@router.post(
    "/mcp/action-incidents/{incident_id}/reconcile",
    response_model=McpActionIncidentView,
)
def reconcile_mcp_action_incident(
    incident_id: UUID,
    payload: McpActionIncidentReconcile,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> McpActionIncidentView:
    ensure_mcp_approver(principal)
    service = McpActionIncidentService(db)
    ensure_business_unit_access(
        principal,
        service.get(incident_id).business_unit_id,
    )
    return service.reconcile(
        incident_id,
        payload,
        actor_id=principal.actor_id,
        correlation_id=correlation_id(request),
    )


@router.post(
    "/mcp/action-incidents/{incident_id}/compensation-requests",
    response_model=McpActionIncidentView,
)
def request_mcp_action_compensation(
    incident_id: UUID,
    payload: McpActionIncidentCompensation,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> McpActionIncidentView:
    ensure_mcp_approver(principal)
    service = McpActionIncidentService(db)
    ensure_business_unit_access(
        principal,
        service.get(incident_id).business_unit_id,
    )
    return service.request_compensation(
        incident_id,
        payload,
        actor_id=principal.actor_id,
        correlation_id=correlation_id(request),
    )

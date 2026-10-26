from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from ticket_agent.agent_runs.schemas import AgentRunListResponse, AgentRunTraceResponse
from ticket_agent.agent_runs.service import AgentRunService
from ticket_agent.api.dependencies import Actor, DbSession
from ticket_agent.digital_employees.service import DigitalEmployeeService
from ticket_agent.identity.dependencies import (
    ensure_business_unit_access,
    ensure_metrics_viewer,
    resolve_business_unit,
)
from ticket_agent.shared.errors import ApiProblem

router = APIRouter()


@router.get("/agent-runs", response_model=AgentRunListResponse)
def list_agent_runs(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
    employee_id: Annotated[UUID | None, Query()] = None,
    ticket_id: Annotated[UUID | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AgentRunListResponse:
    ensure_metrics_viewer(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    if employee_id is not None:
        employee = DigitalEmployeeService(db).get(employee_id)
        ensure_business_unit_access(principal, employee.business_unit_id)
    items, total = AgentRunService(db).list_runs(
        business_unit_id=business_unit_id,
        employee_id=employee_id,
        ticket_id=ticket_id,
        status=status,
        limit=limit,
    )
    return AgentRunListResponse(items=items, total=total)


@router.get("/agent-runs/{run_id}/trace", response_model=AgentRunTraceResponse)
def get_agent_run_trace(
    run_id: UUID,
    db: DbSession,
    principal: Actor,
) -> AgentRunTraceResponse:
    ensure_metrics_viewer(principal)
    trace = AgentRunService(db).trace(run_id, principal=principal)
    if trace is None:
        raise ApiProblem(
            status_code=404,
            code="RESOURCE_NOT_FOUND",
            title="Agent run not found",
            detail=f"Agent run {run_id} does not exist.",
        )
    return trace

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import ColumnElement, func, select

from ticket_agent.api.dependencies import Actor, DbSession
from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.digital_employees.service import DigitalEmployeeService
from ticket_agent.identity.dependencies import (
    ensure_business_unit_access,
    ensure_metrics_viewer,
    resolve_business_unit,
)
from ticket_agent.tools.api_schemas import (
    ToolCallListResponse,
    ToolCallView,
    ToolMetricsResponse,
)
from ticket_agent.tools.metrics import ToolMetricsService
from ticket_agent.tools.models import ToolCall

router = APIRouter()


@router.get("/tool-calls", response_model=ToolCallListResponse)
def list_tool_calls(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
    ticket_id: Annotated[UUID | None, Query()] = None,
    employee_id: Annotated[UUID | None, Query()] = None,
    tool_key: Annotated[str | None, Query()] = None,
    call_status: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> ToolCallListResponse:
    ensure_metrics_viewer(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    employee_ids = select(DigitalEmployee.id).where(
        DigitalEmployee.business_unit_id == business_unit_id
    )
    filters: list[ColumnElement[bool]] = [
        ToolCall.employee_id.in_(employee_ids)
    ]
    if ticket_id:
        filters.append(ToolCall.ticket_id == ticket_id)
    if employee_id:
        employee = DigitalEmployeeService(db).get(employee_id)
        ensure_business_unit_access(principal, employee.business_unit_id)
        filters.append(ToolCall.employee_id == employee_id)
    if tool_key:
        filters.append(ToolCall.tool_key == tool_key)
    if call_status:
        filters.append(ToolCall.status == call_status)
    total = db.scalar(select(func.count()).select_from(ToolCall).where(*filters)) or 0
    calls = db.scalars(
        select(ToolCall)
        .where(*filters)
        .order_by(ToolCall.started_at.desc())
        .limit(limit)
    ).all()
    return ToolCallListResponse(
        items=[_call_view(call) for call in calls],
        total=total,
    )


@router.get("/metrics/tools", response_model=ToolMetricsResponse)
def get_tool_metrics(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
    from_at: Annotated[datetime | None, Query()] = None,
    to_at: Annotated[datetime | None, Query()] = None,
) -> ToolMetricsResponse:
    ensure_metrics_viewer(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    payload = ToolMetricsService(db).summary(
        business_unit_id=business_unit_id,
        from_at=from_at,
        to_at=to_at,
    )
    return ToolMetricsResponse.model_validate(payload)


def _call_view(call: ToolCall) -> ToolCallView:
    duration_ms = (
        max(0.0, (call.completed_at - call.started_at).total_seconds() * 1000)
        if call.completed_at
        else None
    )
    return ToolCallView(
        id=call.id,
        employee_id=call.employee_id,
        ticket_id=call.ticket_id,
        tool_key=call.tool_key,
        action_type=call.action_type,
        risk_level=call.risk_level,
        status=call.status,
        correlation_id=call.correlation_id,
        request_payload=call.request_payload,
        response_summary=call.response_summary,
        error_code=call.error_code,
        error_message=call.error_message,
        started_at=call.started_at,
        completed_at=call.completed_at,
        duration_ms=duration_ms,
    )


from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ticket_agent.agent_runs.models import AgentRun
from ticket_agent.agent_runs.schemas import (
    AgentRunTraceResponse,
    AgentRunView,
    AgentTraceEvent,
)
from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.identity.dependencies import ensure_business_unit_access
from ticket_agent.identity.models import Principal
from ticket_agent.model_gateway.models import ModelCall
from ticket_agent.tickets.models import AuditEvent, Ticket, WorkflowTransition
from ticket_agent.tools.models import ToolCall


class AgentRunService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def start_ticket_run(
        self,
        *,
        ticket: Ticket,
        employee: DigitalEmployee,
        correlation_id: str,
    ) -> AgentRun:
        existing = self.session.scalar(
            select(AgentRun).where(AgentRun.correlation_id == correlation_id)
        )
        if existing is not None:
            return existing
        run = AgentRun(
            business_unit_id=ticket.business_unit_id,
            employee_id=employee.id,
            ticket_id=ticket.id,
            run_type="ticket_processing",
            workflow_key=employee.workflow_key,
            status="RUNNING",
            correlation_id=correlation_id,
            input_summary={
                "subject": ticket.subject,
                "source_system": ticket.source_system,
                "external_ticket_id": ticket.source_ticket_id,
            },
        )
        self.session.add(run)
        self.session.flush()
        return run

    def finish_ticket_run(self, run: AgentRun, ticket: Ticket) -> None:
        run.status = (
            "WAITING_HUMAN" if ticket.needs_human else "SUCCEEDED"
        )
        run.result_summary = {
            "workflow_state": ticket.workflow_state,
            "ticket_status": ticket.status,
            "category_primary": ticket.category_primary,
            "risk_level": ticket.risk_level,
            "priority": ticket.priority,
            "queue_id": ticket.queue_id,
            "needs_human": ticket.needs_human,
            "human_reason": ticket.human_reason,
        }
        run.completed_at = datetime.now(UTC)

    def fail_run(self, run: AgentRun, error: Exception) -> None:
        run.status = "FAILED"
        run.error_code = type(error).__name__
        run.error_message = str(error)[:2000]
        run.completed_at = datetime.now(UTC)

    def list_runs(
        self,
        *,
        business_unit_id: str | None = None,
        employee_id: UUID | None = None,
        ticket_id: UUID | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> tuple[list[AgentRunView], int]:
        filters = []
        if business_unit_id:
            filters.append(AgentRun.business_unit_id == business_unit_id)
        if employee_id:
            filters.append(AgentRun.employee_id == employee_id)
        if ticket_id:
            filters.append(AgentRun.ticket_id == ticket_id)
        if status:
            filters.append(AgentRun.status == status)
        total = self.session.scalar(
            select(func.count()).select_from(AgentRun).where(*filters)
        ) or 0
        rows = self.session.execute(
            select(AgentRun, DigitalEmployee, Ticket)
            .join(DigitalEmployee, DigitalEmployee.id == AgentRun.employee_id)
            .outerjoin(Ticket, Ticket.id == AgentRun.ticket_id)
            .where(*filters)
            .order_by(AgentRun.started_at.desc())
            .limit(limit)
        ).all()
        return [
            _run_view(run, employee, ticket) for run, employee, ticket in rows
        ], total

    def trace(
        self,
        run_id: UUID,
        *,
        principal: Principal,
    ) -> AgentRunTraceResponse | None:
        row = self.session.execute(
            select(AgentRun, DigitalEmployee, Ticket)
            .join(DigitalEmployee, DigitalEmployee.id == AgentRun.employee_id)
            .outerjoin(Ticket, Ticket.id == AgentRun.ticket_id)
            .where(AgentRun.id == run_id)
        ).one_or_none()
        if row is None:
            return None
        run, employee, ticket = row
        ensure_business_unit_access(principal, run.business_unit_id)
        view = _run_view(run, employee, ticket)
        events = [
            AgentTraceEvent(
                id=f"run:{run.id}",
                event_type="run",
                title="数字员工开始处理",
                status=run.status,
                timestamp=_as_utc(run.started_at),
                duration_ms=view.duration_ms,
                detail={
                    "employee": employee.name,
                    "workflow_key": run.workflow_key,
                    "input": run.input_summary,
                    "result": run.result_summary,
                    "error": run.error_message,
                },
            )
        ]
        if run.ticket_id is None:
            return AgentRunTraceResponse(run=view, events=events)

        end_at = run.completed_at or datetime.now(UTC)
        start_at = _as_utc(run.started_at)
        transitions = self.session.scalars(
            select(WorkflowTransition)
            .where(
                WorkflowTransition.ticket_id == run.ticket_id,
                WorkflowTransition.created_at >= start_at,
                WorkflowTransition.created_at <= end_at,
            )
            .order_by(WorkflowTransition.created_at)
        ).all()
        for transition in transitions:
            events.append(
                AgentTraceEvent(
                    id=f"workflow:{transition.id}",
                    event_type="workflow",
                    title=(
                        f"{transition.from_state} → {transition.to_state}"
                    ),
                    status="SUCCEEDED",
                    timestamp=_as_utc(transition.created_at),
                    detail={"reason_code": transition.reason_code},
                )
            )

        tool_calls = self.session.scalars(
            select(ToolCall)
            .where(
                ToolCall.ticket_id == run.ticket_id,
                ToolCall.started_at >= start_at,
                ToolCall.started_at <= end_at,
            )
            .order_by(ToolCall.started_at)
        ).all()
        for tool_call in tool_calls:
            events.append(
                AgentTraceEvent(
                    id=f"tool:{tool_call.id}",
                    event_type="tool",
                    title=tool_call.tool_key,
                    status=tool_call.status,
                    timestamp=_as_utc(tool_call.started_at),
                    duration_ms=_duration_ms(
                        tool_call.started_at,
                        tool_call.completed_at,
                    ),
                    detail={
                        "risk_level": tool_call.risk_level,
                        "request": tool_call.request_payload,
                        "response": tool_call.response_summary,
                        "error": tool_call.error_message,
                    },
                )
            )

        model_calls = self.session.scalars(
            select(ModelCall)
            .where(
                ModelCall.ticket_id == run.ticket_id,
                ModelCall.started_at >= start_at,
                ModelCall.started_at <= end_at,
            )
            .order_by(ModelCall.started_at)
        ).all()
        for model_call in model_calls:
            events.append(
                AgentTraceEvent(
                    id=f"model:{model_call.id}",
                    event_type="model",
                    title=f"{model_call.purpose} · {model_call.model_name}",
                    status=model_call.status,
                    timestamp=_as_utc(model_call.started_at),
                    duration_ms=model_call.latency_ms,
                    detail={
                        "provider": model_call.provider,
                        "input_tokens": model_call.input_tokens,
                        "output_tokens": model_call.output_tokens,
                        "total_tokens": model_call.total_tokens,
                        "estimated_cost": model_call.estimated_cost,
                        "error_code": model_call.error_code,
                    },
                )
            )

        audit_events = self.session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.resource_id == str(run.ticket_id),
                AuditEvent.occurred_at >= start_at,
                AuditEvent.occurred_at <= end_at,
            )
            .order_by(AuditEvent.occurred_at)
        ).all()
        for event in audit_events:
            events.append(
                AgentTraceEvent(
                    id=f"audit:{event.id}",
                    event_type="audit",
                    title=event.event_type,
                    status=event.decision,
                    timestamp=_as_utc(event.occurred_at),
                    detail={
                        "actor": event.actor_id,
                        "action": event.action,
                        "reason_code": event.reason_code,
                        "payload": event.redacted_payload,
                    },
                )
            )
        events.sort(key=lambda event: event.timestamp)
        return AgentRunTraceResponse(run=view, events=events)


def _run_view(
    run: AgentRun,
    employee: DigitalEmployee,
    ticket: Ticket | None,
) -> AgentRunView:
    return AgentRunView(
        id=run.id,
        business_unit_id=run.business_unit_id,
        employee_id=run.employee_id,
        employee_name=employee.name,
        employee_key=employee.employee_key,
        ticket_id=run.ticket_id,
        ticket_subject=ticket.subject if ticket else None,
        run_type=run.run_type,
        workflow_key=run.workflow_key,
        status=run.status,
        correlation_id=run.correlation_id,
        input_summary=run.input_summary,
        result_summary=run.result_summary,
        error_code=run.error_code,
        error_message=run.error_message,
        started_at=_as_utc(run.started_at),
        completed_at=_as_utc(run.completed_at) if run.completed_at else None,
        duration_ms=_duration_ms(run.started_at, run.completed_at),
    )


def _duration_ms(started_at: datetime, completed_at: datetime | None) -> int | None:
    if completed_at is None:
        return None
    return max(
        0,
        round(
            (
                _as_utc(completed_at) - _as_utc(started_at)
            ).total_seconds()
            * 1000
        ),
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)

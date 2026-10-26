from uuid import UUID

from ticket_agent.agent_runs.models import AgentRun
from ticket_agent.agent_runs.service import AgentRunService
from ticket_agent.digital_employees.service import DigitalEmployeeService
from ticket_agent.shared.db import SessionLocal
from ticket_agent.tickets.domain import WorkflowState
from ticket_agent.tickets.models import Ticket
from ticket_agent.workflow.registry import get_workflow


def process_ticket_job(ticket_id: UUID, correlation_id: str) -> None:
    """Initial in-process worker boundary; replace with Celery dispatch later."""
    with SessionLocal() as session:
        ticket = session.get(Ticket, ticket_id)
        if ticket is None:
            return
        if ticket.workflow_state != WorkflowState.RECEIVED:
            return
        employee_service = DigitalEmployeeService(session)
        employee = (
            employee_service.get(ticket.employee_id)
            if ticket.employee_id is not None
            else employee_service.ensure_default(ticket.business_unit_id)
        )
        run_service = AgentRunService(session)
        run = run_service.start_ticket_run(
            ticket=ticket,
            employee=employee,
            correlation_id=correlation_id,
        )
        session.commit()
        run_id = run.id
        try:
            get_workflow(session, employee.workflow_key).process(
                ticket_id,
                correlation_id,
            )
            session.refresh(ticket)
            completed_run = session.get(AgentRun, run_id)
            if completed_run is not None:
                run_service.finish_ticket_run(completed_run, ticket)
                session.commit()
        except Exception as exc:
            session.rollback()
            with SessionLocal() as failure_session:
                failed_run = failure_session.get(AgentRun, run_id)
                if failed_run is not None:
                    AgentRunService(failure_session).fail_run(failed_run, exc)
                    failure_session.commit()
            raise


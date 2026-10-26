from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ticket_agent.audit.service import record_audit
from ticket_agent.digital_employees.service import DigitalEmployeeService
from ticket_agent.integrations.factory import get_ticket_adapter
from ticket_agent.integrations.types import (
    TicketAdapter,
    TicketIntegrationError,
    TicketSyncPayload,
)
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import get_settings
from ticket_agent.tickets.domain import TicketStatus, WorkflowState
from ticket_agent.tickets.models import AnswerDraft, Ticket, WorkflowTransition
from ticket_agent.tools.execution import ToolExecutionService
from ticket_agent.tools.registry import ToolPermissionError


class TicketSyncService:
    def __init__(
        self,
        session: Session,
        *,
        adapter: TicketAdapter | None = None,
    ) -> None:
        self.session = session
        self.adapter = adapter or get_ticket_adapter()
        self.settings = get_settings()
        self.tool_execution = ToolExecutionService(session)

    def sync(self, ticket_id: UUID, correlation_id: str) -> None:
        ticket = self.session.scalar(
            select(Ticket).where(Ticket.id == ticket_id).with_for_update()
        )
        if ticket is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Ticket not found",
                detail=f"Ticket {ticket_id} does not exist.",
            )
        if ticket.sync_status == "SUCCEEDED":
            return
        if ticket.workflow_state != WorkflowState.SYNCING:
            return
        draft = self.session.scalar(
            select(AnswerDraft)
            .where(AnswerDraft.ticket_id == ticket.id)
            .order_by(AnswerDraft.created_at.desc())
            .limit(1)
        )
        if draft is None:
            self._fail_terminal(ticket, correlation_id, "DRAFT_NOT_FOUND")
            return
        employee_service = DigitalEmployeeService(self.session)
        employee = (
            employee_service.get(ticket.employee_id)
            if ticket.employee_id is not None
            else employee_service.ensure_default(ticket.business_unit_id)
        )
        human_approved = draft.status in {"ACCEPTED", "EDITED_AND_ACCEPTED"}
        policy_approved = (
            draft.status == "AUTO_ACCEPTED"
            and ticket.category_primary == "ecommerce_presales"
            and ticket.risk_level == "R0"
            and not ticket.needs_human
        )
        approval_source = (
            "HUMAN"
            if human_approved
            else "LOW_RISK_POLICY"
            if policy_approved
            else None
        )
        idempotency_key = f"ticket-sync:{ticket.id}:{draft.id}"
        try:
            sync_call, _definition, _sync_payload = self.tool_execution.begin(
                employee=employee,
                tool_key="ticket.sync",
                payload={
                    "ticket_id": str(ticket.id),
                    "external_ticket_id": ticket.source_ticket_id,
                    "idempotency_key": idempotency_key,
                },
                correlation_id=correlation_id,
                ticket_id=ticket.id,
                human_approved=human_approved,
                policy_approved=policy_approved,
            )
        except ToolPermissionError as exc:
            ticket.sync_error = str(exc)
            self._fail_terminal(ticket, correlation_id, exc.code)
            return

        ticket.sync_attempts += 1
        ticket.sync_status = "SYNCING"
        ticket.sync_error = None
        payload = TicketSyncPayload(
            external_ticket_id=ticket.source_ticket_id,
            category_primary=ticket.category_primary or "other_unclassified",
            category_secondary=ticket.category_secondary or "unknown",
            priority=ticket.priority or "P2",
            risk_level=ticket.risk_level or "R1",
            queue_id=ticket.queue_id or "MANUAL_TRIAGE",
            response_text=draft.text,
            citations=draft.citations_json,
        )
        self.session.commit()
        attempt_number = ticket.sync_attempts

        try:
            result = self.adapter.get_sync_result(
                external_ticket_id=payload.external_ticket_id,
                idempotency_key=idempotency_key,
            )
            if result is None:
                result = self.adapter.sync_ticket(
                    payload=payload,
                    idempotency_key=idempotency_key,
                )
        except TicketIntegrationError as exc:
            self.tool_execution.fail(
                sync_call,
                error_code=(
                    "RETRYABLE_EXTERNAL_ERROR"
                    if exc.retryable
                    else "EXTERNAL_SYNC_FAILED"
                ),
                error_message=str(exc),
            )
            should_retry = (
                exc.retryable
                and attempt_number < self.settings.ticket_sync_max_attempts
            )
            self._handle_failure(
                ticket.id,
                correlation_id,
                str(exc),
                retryable=should_retry,
            )
            if should_retry:
                raise
            return
        except Exception as exc:
            self.tool_execution.fail(
                sync_call,
                error_code="EXTERNAL_SYNC_FAILED",
                error_message=str(exc),
            )
            should_retry = attempt_number < self.settings.ticket_sync_max_attempts
            self._handle_failure(
                ticket.id,
                correlation_id,
                str(exc),
                retryable=should_retry,
            )
            if should_retry:
                raise
            return

        self.tool_execution.succeed(
            sync_call,
            {
                "external_request_id": result.external_request_id,
                "attempt": attempt_number,
                "approval_source": approval_source,
            },
        )

        ticket = self.session.scalar(
            select(Ticket).where(Ticket.id == ticket_id).with_for_update()
        )
        if ticket is None:
            return
        previous_state = ticket.workflow_state
        ticket.sync_status = "SUCCEEDED"
        ticket.sync_error = None
        ticket.external_request_id = result.external_request_id
        ticket.external_synced_at = datetime.now(UTC)
        ticket.workflow_state = WorkflowState.COMPLETED
        ticket.status = TicketStatus.RESOLVED
        ticket.version += 1
        self.session.add(
            WorkflowTransition(
                ticket_id=ticket.id,
                from_state=previous_state,
                to_state=WorkflowState.COMPLETED,
                reason_code="EXTERNAL_SYNC_SUCCEEDED",
                actor_type="SERVICE",
                actor_id="digital_agent.ticket.v1",
            )
        )
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="ticket.external_sync_succeeded",
            actor_type="SERVICE",
            actor_id="digital_agent.ticket.v1",
            resource_id=ticket.id,
            action="sync",
            decision="EXECUTED",
            payload={
                "adapter": self.adapter.name,
                "external_request_id": result.external_request_id,
                "attempt": ticket.sync_attempts,
            },
        )
        self.session.commit()

    def _handle_failure(
        self,
        ticket_id: UUID,
        correlation_id: str,
        error: str,
        *,
        retryable: bool,
    ) -> None:
        ticket = self.session.scalar(
            select(Ticket).where(Ticket.id == ticket_id).with_for_update()
        )
        if ticket is None:
            return
        ticket.sync_error = error[:2000]
        if not retryable:
            self._fail_terminal(ticket, correlation_id, "EXTERNAL_SYNC_FAILED")
            return
        ticket.sync_status = "RETRYING"
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="ticket.external_sync_failed",
            actor_type="SERVICE",
            actor_id="digital_agent.ticket.v1",
            resource_id=ticket.id,
            action="sync",
            decision="DENY",
            reason_code="RETRYABLE_EXTERNAL_ERROR",
            payload={
                "adapter": self.adapter.name,
                "attempt": ticket.sync_attempts,
                "error": ticket.sync_error,
            },
        )
        self.session.commit()

    def _fail_terminal(
        self,
        ticket: Ticket,
        correlation_id: str,
        reason_code: str,
    ) -> None:
        previous_state = ticket.workflow_state
        ticket.sync_status = "FAILED"
        ticket.sync_error = ticket.sync_error or reason_code
        ticket.workflow_state = WorkflowState.NEEDS_HUMAN
        ticket.status = TicketStatus.WAITING_HUMAN
        ticket.needs_human = True
        ticket.human_reason = reason_code
        ticket.version += 1
        self.session.add(
            WorkflowTransition(
                ticket_id=ticket.id,
                from_state=previous_state,
                to_state=WorkflowState.NEEDS_HUMAN,
                reason_code=reason_code,
                actor_type="SERVICE",
                actor_id="digital_agent.ticket.v1",
            )
        )
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="ticket.external_sync_failed",
            actor_type="SERVICE",
            actor_id="digital_agent.ticket.v1",
            resource_id=ticket.id,
            action="sync",
            decision="DENY",
            reason_code=reason_code,
            payload={
                "adapter": self.adapter.name,
                "attempt": ticket.sync_attempts,
                "error": ticket.sync_error,
            },
        )
        self.session.commit()


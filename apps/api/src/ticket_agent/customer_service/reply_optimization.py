from uuid import UUID

from sqlalchemy.orm import Session

from ticket_agent.audit.service import record_audit
from ticket_agent.customer_service.models import CustomerConversation
from ticket_agent.customer_service.schemas import (
    CustomerReplyOptimizationCreate,
    CustomerReplyOptimizationView,
)
from ticket_agent.digital_employees.service import DigitalEmployeeService
from ticket_agent.model_gateway.profile import (
    build_reply_optimizer_for_employee,
)
from ticket_agent.model_gateway.types import ModelGatewayError
from ticket_agent.model_gateway.usage import ModelUsageGuard
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.tickets.models import Ticket


class CustomerReplyOptimizationService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def optimize(
        self,
        conversation_id: UUID,
        payload: CustomerReplyOptimizationCreate,
        *,
        agent_id: str,
        correlation_id: str,
    ) -> CustomerReplyOptimizationView:
        conversation = self.session.get(CustomerConversation, conversation_id)
        if conversation is None:
            raise ApiProblem(
                status_code=404,
                code="CONVERSATION_NOT_FOUND",
                title="Conversation not found",
                detail="The conversation does not exist.",
            )
        if conversation.assigned_agent_id != agent_id:
            raise ApiProblem(
                status_code=409,
                code="CONVERSATION_NOT_ASSIGNED_TO_AGENT",
                title="Conversation is not assigned to this agent",
                detail="Take over the conversation before optimizing a reply.",
            )
        ticket = (
            self.session.get(Ticket, conversation.current_ticket_id)
            if conversation.current_ticket_id
            else None
        )
        employee_service = DigitalEmployeeService(self.session)
        employee = (
            employee_service.get(ticket.employee_id)
            if ticket and ticket.employee_id
            else employee_service.ensure_default(conversation.business_unit_id)
        )
        usage_guard = ModelUsageGuard(
            self.session,
            employee=employee,
            ticket_id=ticket.id if ticket else None,
            correlation_id=correlation_id,
        )
        try:
            optimizer = build_reply_optimizer_for_employee(
                employee,
                usage_guard=usage_guard,
            )
            optimized_text = optimizer.optimize_reply(
                text=payload.text.strip(),
                style=payload.style,
            )
        except ValueError as exc:
            raise ApiProblem(
                status_code=409,
                code="REPLY_OPTIMIZATION_MODEL_NOT_CONFIGURED",
                title="Reply optimization model is not configured",
                detail=str(exc),
            ) from exc
        except ModelGatewayError as exc:
            raise ApiProblem(
                status_code=502,
                code=exc.code,
                title="Reply optimization failed",
                detail=str(exc),
                retryable=exc.retryable,
            ) from exc
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="customer_service.reply_optimized",
            actor_type="USER",
            actor_id=agent_id,
            resource_type="customer_conversation",
            resource_id=conversation.id,
            action="optimize_reply",
            decision="EXECUTED",
            payload={
                "ticket_id": str(ticket.id) if ticket else None,
                "provider": optimizer.settings.model_provider,
                "model": optimizer.settings.model_name,
                "style": payload.style,
                "input_length": len(payload.text),
            },
        )
        self.session.commit()
        return CustomerReplyOptimizationView(
            text=optimized_text,
            provider=optimizer.settings.model_provider,
            model=optimizer.settings.model_name,
        )

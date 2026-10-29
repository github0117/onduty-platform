from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ticket_agent.classification.classifier import AnalysisResult
from ticket_agent.customer_service.domain import (
    TERMINAL_TURN_STATUSES,
    TurnStatus,
    parse_turn_status,
)
from ticket_agent.customer_service.models import (
    ConversationMemory,
    ConversationTurn,
    CustomerConversation,
    CustomerMessage,
)
from ticket_agent.customer_service.service import CustomerConversationService
from ticket_agent.customer_service.streaming import stream_text
from ticket_agent.customer_service.suggestions import (
    CustomerReplySuggestionService,
)
from ticket_agent.customer_service.turn_events import (
    new_lease,
    record_turn_event,
    transition_turn,
)
from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.ecommerce.models import EcommerceCategoryProfile
from ticket_agent.model_gateway.profile import build_classifier_for_employee
from ticket_agent.routing.policy import get_routing_policy
from ticket_agent.shared.db import SessionLocal
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import get_settings
from ticket_agent.tickets.domain import TicketStatus, WorkflowState
from ticket_agent.tickets.models import Ticket
from ticket_agent.tickets.transitions import transition_ticket


class ConversationTurnOrchestrator:
    def __init__(self, session: Session) -> None:
        self.session = session

    def process(
        self,
        turn_id: UUID,
        *,
        correlation_id: str,
        on_stage: Callable[[str], None] | None = None,
        on_text_delta: Callable[[str], None] | None = None,
        on_text_replace: Callable[[str], None] | None = None,
    ) -> None:
        turn = self.session.scalar(
            select(ConversationTurn)
            .where(ConversationTurn.id == turn_id)
            .with_for_update()
        )
        if turn is None:
            return
        status = parse_turn_status(turn.status)
        if status in TERMINAL_TURN_STATUSES:
            # Duplicate dispatch after the turn already finished: idempotent.
            return
        if status == TurnStatus.FAILED_RETRYABLE:
            # Only the reclaim job moves a retryable turn back to PENDING.
            return
        now = datetime.now(UTC)
        if (
            status == TurnStatus.RUNNING
            and turn.lease_expires_at is not None
            and turn.lease_expires_at > now
        ):
            # Another worker still owns this turn; let it finish.
            return
        conversation = self.session.get(
            CustomerConversation,
            turn.conversation_id,
        )
        user_message = self.session.get(
            CustomerMessage,
            turn.user_message_id,
        )
        if conversation is None or user_message is None:
            return
        lease_seconds = get_settings().conversation_turn_lease_seconds
        turn.lease_expires_at = new_lease(lease_seconds, now=now)
        if turn.correlation_id is None:
            turn.correlation_id = correlation_id
        if status == TurnStatus.PENDING:
            turn.attempt_count += 1
            transition_turn(
                self.session,
                turn,
                TurnStatus.RUNNING,
                reason_code="TURN_DISPATCHED",
                actor_id="digital_employee.runtime",
                correlation_id=correlation_id,
                stage_label="正在识别问题",
                payload={"attempt_count": turn.attempt_count},
            )
        else:
            record_turn_event(
                self.session,
                turn,
                event_type="TURN_RESUMED",
                actor_id="digital_employee.runtime",
                correlation_id=correlation_id,
                payload={
                    "attempt_count": turn.attempt_count,
                    "reason_code": "TURN_LEASE_EXPIRED",
                },
            )
        self.session.commit()
        ticket = (
            self.session.get(Ticket, turn.ticket_id)
            if turn.ticket_id is not None
            else None
        )
        employee = (
            self.session.get(DigitalEmployee, turn.employee_id)
            if turn.employee_id is not None
            else None
        )
        if ticket is None or employee is None:
            self._fail(
                turn,
                conversation,
                "TURN_CONTEXT_MISSING",
                "本轮缺少工单或数字员工上下文。",
                retryable=False,
            )
            return

        streamed_parts: list[str] = []

        def emit_stage(label: str) -> None:
            turn.stage_label = label
            if on_stage is not None:
                on_stage(label)

        def emit_delta(delta: str) -> None:
            if not delta:
                return
            streamed_parts.append(delta)
            if on_text_delta is not None:
                on_text_delta(delta)

        emit_stage("正在识别问题")
        turn.started_at = datetime.now(UTC)
        self.session.commit()

        analysis = build_classifier_for_employee(employee).classify(
            subject=user_message.content[:120],
            body=user_message.content,
            customer_tier=ticket.customer_tier,
        )
        analysis = self._apply_category_profile(
            ticket,
            analysis,
            text=user_message.content,
        )
        self._apply_analysis(ticket, analysis)
        turn.analysis_json = self._analysis_payload(analysis)
        turn.intent = analysis.category_primary
        emit_stage("正在检索知识并处理")
        memory = self.session.get(ConversationMemory, conversation.id)
        history_count = (
            self.session.scalar(
                select(func.count())
                .select_from(CustomerMessage)
                .where(CustomerMessage.conversation_id == conversation.id)
            )
            or 0
        )
        record_turn_event(
            self.session,
            turn,
            event_type="CONTEXT_ASSEMBLED",
            actor_id="digital_employee.runtime",
            correlation_id=correlation_id,
            payload={
                "history_message_count": history_count,
                "memory_last_turn_sequence": (
                    memory.last_turn_sequence if memory is not None else 0
                ),
                "employee_id": str(ticket.employee_id)
                if ticket.employee_id
                else None,
                "employee_config_revision": turn.employee_config_revision,
            },
        )
        self.session.commit()

        try:
            suggestion = CustomerReplySuggestionService(
                self.session,
                on_stage=on_stage,
                on_text_delta=(
                    emit_delta if on_text_delta is not None else None
                ),
            ).generate(
                conversation.id,
                agent_id="digital_employee.runtime",
                correlation_id=correlation_id,
            )
        except ApiProblem as exc:
            # Business-level rejections (no knowledge, no skill, missing
            # context) are terminal: re-running the same turn cannot fix them.
            # Only explicitly transient problems are retried.
            self._fail(
                turn,
                conversation,
                exc.code,
                exc.detail,
                retryable=exc.retryable,
            )
            return
        except Exception as exc:
            self._fail(
                turn,
                conversation,
                "TURN_PROCESSING_FAILED",
                f"处理失败：{type(exc).__name__}",
            )
            return

        assistant_content = suggestion.text
        if on_text_delta is not None:
            streamed_text = "".join(streamed_parts)
            if not streamed_text:
                stream_text(assistant_content, emit_delta)
            elif (
                streamed_text != assistant_content
                and on_text_replace is not None
            ):
                on_text_replace(assistant_content)

        assistant = CustomerConversationService(
            self.session
        ).append_assistant_message(
            conversation_id=conversation.id,
            ticket_id=ticket.id,
            content=assistant_content,
        )
        CustomerConversationService(self.session).complete_turn(
            turn_id=turn.id,
            assistant_message=assistant,
            response_provider=suggestion.provider,
            response_model=suggestion.model,
            grounding_status=suggestion.grounding_status,
            citations=suggestion.citations,
            trace=suggestion.trace,
            tool_calls=suggestion.tool_calls,
            intent=analysis.category_primary,
            analysis=self._analysis_payload(analysis),
            correlation_id=correlation_id,
        )
        if _can_complete_grounded_turn(
            ticket,
            suggestion.grounding_status,
        ):
            ticket.status = TicketStatus.RESOLVED
            transition_ticket(
                self.session,
                ticket,
                WorkflowState.COMPLETED,
                reason_code="GROUNDED_TURN_COMPLETED",
                actor_id="digital_employee.runtime",
            )
        elif ticket.needs_human:
            ticket.status = TicketStatus.WAITING_HUMAN
            transition_ticket(
                self.session,
                ticket,
                WorkflowState.NEEDS_HUMAN,
                reason_code=ticket.human_reason or "TURN_NEEDS_HUMAN",
                actor_id="digital_employee.runtime",
            )
        else:
            ticket.status = TicketStatus.IN_PROGRESS
            transition_ticket(
                self.session,
                ticket,
                WorkflowState.PENDING_REVIEW,
                reason_code="TURN_PENDING_REVIEW",
                actor_id="digital_employee.runtime",
            )
        ticket.version += 1
        conversation.version += 1
        self.session.commit()

    def _apply_category_profile(
        self,
        ticket: Ticket,
        analysis: AnalysisResult,
        *,
        text: str,
    ) -> AnalysisResult:
        if (
            analysis.risk_level == "R3"
            or analysis.category_primary == "data_privacy_security"
        ):
            return analysis
        category_name = ticket.external_metadata.get("category")
        if not isinstance(category_name, str):
            return analysis
        profile = self.session.scalar(
            select(EcommerceCategoryProfile).where(
                EcommerceCategoryProfile.business_unit_id
                == ticket.business_unit_id,
                EcommerceCategoryProfile.name == category_name,
                EcommerceCategoryProfile.status == "ACTIVE",
            )
        )
        if profile is None:
            return analysis
        if any(
            keyword in text
            for keyword in profile.aftersales_keywords_json
        ):
            return replace(
                analysis,
                category_primary="ecommerce_aftersales",
                category_secondary="category_after_sales",
                confidence=max(analysis.confidence, 0.93),
                needs_human=True,
                human_reason="AFTER_SALES_REQUIRES_HUMAN",
                reason_codes=[
                    *analysis.reason_codes,
                    "CATEGORY_AFTERSALES_KEYWORD",
                ],
            )
        if (
            analysis.risk_level not in {"R2", "R3"}
            and any(
                keyword in text
                for keyword in profile.presales_keywords_json
            )
        ):
            return replace(
                analysis,
                category_primary="ecommerce_presales",
                category_secondary="category_presales",
                confidence=max(analysis.confidence, 0.94),
                needs_human=False,
                human_reason=None,
                reason_codes=[
                    *analysis.reason_codes,
                    "CATEGORY_PRESALES_KEYWORD",
                ],
            )
        return analysis

    def _apply_analysis(
        self,
        ticket: Ticket,
        analysis: AnalysisResult,
    ) -> None:
        routing = get_routing_policy().decide(analysis)
        ticket.category_primary = analysis.category_primary
        ticket.category_secondary = analysis.category_secondary
        ticket.confidence = analysis.confidence
        ticket.summary = analysis.summary
        ticket.risk_level = analysis.risk_level
        ticket.priority = routing.priority
        ticket.queue_id = routing.queue_id
        ticket.needs_human = routing.needs_human
        ticket.human_reason = routing.human_reason
        if routing.needs_human:
            ticket.status = TicketStatus.WAITING_HUMAN
            transition_ticket(
                self.session,
                ticket,
                WorkflowState.NEEDS_HUMAN,
                reason_code=(
                    routing.human_reason or "ROUTING_REQUIRES_HUMAN"
                ),
                actor_id="digital_employee.runtime",
            )
        ticket.version += 1

    @staticmethod
    def _analysis_payload(analysis: AnalysisResult) -> dict[str, object]:
        return {
            "category_primary": analysis.category_primary,
            "category_secondary": analysis.category_secondary,
            "confidence": analysis.confidence,
            "risk_level": analysis.risk_level,
            "risk_tags": analysis.risk_tags,
            "reason_codes": analysis.reason_codes,
            "summary": analysis.summary,
            "needs_human": analysis.needs_human,
            "human_reason": analysis.human_reason,
            "model_provider": analysis.model_provider,
            "model_name": analysis.model_name,
        }

    def _fail(
        self,
        turn: ConversationTurn,
        conversation: CustomerConversation,
        code: str,
        detail: str,
        *,
        retryable: bool = True,
    ) -> None:
        target = (
            TurnStatus.FAILED_RETRYABLE
            if retryable
            else TurnStatus.FAILED_TERMINAL
        )
        transition_turn(
            self.session,
            turn,
            target,
            reason_code=code,
            actor_id="digital_employee.runtime",
            correlation_id=turn.correlation_id,
            stage_label="处理失败",
            payload={"error_code": code, "retryable": retryable},
        )
        turn.lease_expires_at = None
        turn.error_code = code
        turn.error_message = detail[:2000]
        turn.completed_at = datetime.now(UTC)
        ticket = (
            self.session.get(Ticket, turn.ticket_id)
            if turn.ticket_id is not None
            else None
        )
        if ticket is not None:
            ticket.status = TicketStatus.WAITING_HUMAN
            ticket.needs_human = True
            ticket.human_reason = code
            transition_ticket(
                self.session,
                ticket,
                WorkflowState.NEEDS_HUMAN,
                reason_code=code,
                actor_id="digital_employee.runtime",
            )
            ticket.version += 1
        message = CustomerConversationService(
            self.session
        ).append_assistant_message(
            conversation_id=conversation.id,
            ticket_id=turn.ticket_id,
            content="这次没有安全完成处理，请稍后重试或转人工。",
            created_by="system",
        )
        turn.assistant_message_id = message.id
        conversation.version += 1
        self.session.commit()


def process_conversation_turn(turn_id: UUID, correlation_id: str) -> None:
    with SessionLocal() as session:
        ConversationTurnOrchestrator(session).process(
            turn_id,
            correlation_id=correlation_id,
        )


def process_conversation_turn_stream(
    turn_id: UUID,
    correlation_id: str,
    emit: Callable[[dict[str, object]], None],
) -> None:
    """Run a turn and publish live stage/text events for SSE consumers."""
    with SessionLocal() as session:
        turn = session.get(ConversationTurn, turn_id)
        if turn is None:
            emit(
                {
                    "type": "error",
                    "turn_id": str(turn_id),
                    "message": "TURN_NOT_FOUND",
                }
            )
            return
        conversation_id = turn.conversation_id
        try:
            ConversationTurnOrchestrator(session).process(
                turn_id,
                correlation_id=correlation_id,
                on_stage=lambda label: emit(
                    {
                        "type": "status",
                        "turn_id": str(turn_id),
                        "stage": label,
                    }
                ),
                on_text_delta=lambda text: emit(
                    {
                        "type": "delta",
                        "turn_id": str(turn_id),
                        "text": text,
                    }
                ),
                on_text_replace=lambda text: emit(
                    {
                        "type": "replace",
                        "turn_id": str(turn_id),
                        "text": text,
                    }
                ),
            )
        except Exception as exc:  # pragma: no cover - defensive boundary
            session.rollback()
            emit(
                {
                    "type": "error",
                    "turn_id": str(turn_id),
                    "message": type(exc).__name__,
                }
            )
            return
        try:
            view = CustomerConversationService(session).view(
                CustomerConversationService(session).get(conversation_id)
            )
        except Exception as exc:  # pragma: no cover - defensive boundary
            session.rollback()
            emit(
                {
                    "type": "error",
                    "turn_id": str(turn_id),
                    "message": type(exc).__name__,
                }
            )
            return
        emit(
            {
                "type": "done",
                "turn_id": str(turn_id),
                "conversation": view.model_dump(mode="json"),
            }
        )


def _can_complete_grounded_turn(
    ticket: Ticket,
    grounding_status: str,
) -> bool:
    return (
        grounding_status == "GROUNDED"
        and not ticket.needs_human
        and ticket.risk_level not in {"R2", "R3"}
    )

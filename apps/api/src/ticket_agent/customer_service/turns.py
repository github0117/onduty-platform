from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from time import sleep
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ticket_agent.classification.classifier import AnalysisResult
from ticket_agent.customer_service.context import (
    assemble_context,
)
from ticket_agent.customer_service.domain import (
    TERMINAL_TURN_STATUSES,
    TurnStatus,
    parse_turn_status,
)
from ticket_agent.customer_service.models import (
    ConversationHandoff,
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
from ticket_agent.knowledge.gap_events import record_knowledge_gap
from ticket_agent.model_gateway.profile import build_classifier_for_employee
from ticket_agent.routing.policy import get_routing_policy
from ticket_agent.shared.db import SessionLocal, is_deadlock_error
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import get_settings
from ticket_agent.tickets.domain import TicketStatus, WorkflowState
from ticket_agent.tickets.models import Ticket
from ticket_agent.tickets.transitions import transition_ticket

logger = logging.getLogger(__name__)


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
    ) -> UUID | None:
        """Run one turn.

        Returns the id of the next queued turn of the same conversation, if
        any: turns of one conversation run one at a time, in sequence order.
        """
        turn = self.session.scalar(
            select(ConversationTurn)
            .where(ConversationTurn.id == turn_id)
            .with_for_update()
        )
        if turn is None:
            return None
        status = parse_turn_status(turn.status)
        if status in TERMINAL_TURN_STATUSES:
            # Duplicate dispatch after the turn already finished: idempotent.
            return None
        if status == TurnStatus.FAILED_RETRYABLE:
            # Only the reclaim job moves a retryable turn back to PENDING.
            return None
        now = datetime.now(UTC)
        if (
            status == TurnStatus.RUNNING
            and turn.lease_expires_at is not None
            and turn.lease_expires_at > now
        ):
            # Another worker still owns this turn; let it finish.
            return None
        conversation = self.session.get(
            CustomerConversation,
            turn.conversation_id,
        )
        user_message = self.session.get(
            CustomerMessage,
            turn.user_message_id,
        )
        if conversation is None or user_message is None:
            return None
        if self._blocked_by_earlier_turn(turn, now):
            # One turn at a time per conversation. Leave this turn PENDING with
            # its lease intact: whoever finishes the blocking turn dispatches
            # the queue, and the reclaim job is the backstop.
            self.session.commit()
            return None
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
            return self._next_pending_turn(conversation.id, exclude=turn.id)

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
        context = assemble_context(
            self.session,
            conversation_id=conversation.id,
            current_message=user_message,
        )
        turn.context_json = context.payload
        if context.handoff is not None:
            # This turn is the successor of the recorded handoff: close the
            # link so a reader can go from the turn to the handoff and back.
            turn.handoff_id = context.handoff.id
            handoff_row = self.session.get(
                ConversationHandoff,
                context.handoff.id,
            )
            if handoff_row is not None and handoff_row.to_turn_id is None:
                handoff_row.to_turn_id = turn.id
        record_turn_event(
            self.session,
            turn,
            event_type="CONTEXT_ASSEMBLED",
            actor_id="digital_employee.runtime",
            correlation_id=correlation_id,
            payload={
                **context.payload,
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
                context=context,
            )
        except ApiProblem as exc:
            # Business-level rejections (no knowledge, no skill, missing
            # context) are terminal: re-running the same turn cannot fix them.
            # Only explicitly transient problems are retried.
            if exc.code == "KNOWLEDGE_NOT_FOUND":
                # "We had nothing to answer from" is a knowledge gap, not a
                # broken runtime: record it so repeated questions open a
                # repair task instead of only failing tickets.
                record_knowledge_gap(
                    self.session,
                    business_unit_id=ticket.business_unit_id,
                    query=user_message.content,
                    ticket_id=ticket.id,
                    turn_id=turn.id,
                )
            self._fail(
                turn,
                conversation,
                exc.code,
                exc.detail,
                retryable=exc.retryable,
            )
            return self._next_pending_turn(conversation.id, exclude=turn.id)
        except OperationalError:
            # The database aborted this transaction (a deadlock with a human
            # takeover); every statement in it would fail until rolled back,
            # so recovery belongs to the dispatch boundary, not ``_fail``.
            self.session.rollback()
            raise
        except Exception as exc:
            self._fail(
                turn,
                conversation,
                "TURN_PROCESSING_FAILED",
                f"处理失败：{type(exc).__name__}",
            )
            return self._next_pending_turn(conversation.id, exclude=turn.id)

        # A human may have taken over while the answer was generated. Re-read
        # the row before writing anything the human would talk over.
        self.session.refresh(turn)
        if parse_turn_status(turn.status) is TurnStatus.CANCELLED:
            self.session.rollback()
            return self._next_pending_turn(conversation.id, exclude=turn.id)
        if suggestion.grounding_status == "NO_KNOWLEDGE":
            record_knowledge_gap(
                self.session,
                business_unit_id=ticket.business_unit_id,
                query=user_message.content,
                ticket_id=ticket.id,
                turn_id=turn.id,
            )
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
            turn_id=turn.id,
        )
        try:
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
                skill_snapshot=suggestion.skill_snapshot,
                completion=suggestion.completion,
                gate=suggestion.gate,
                correlation_id=correlation_id,
            )
        except ApiProblem as exc:
            if exc.code != "TURN_CANCELLED":
                raise
            # The takeover cancelled this turn after the row snapshot above;
            # discard the generated message and its events.
            self.session.rollback()
            return self._next_pending_turn(conversation.id, exclude=turn.id)
        if _can_complete_grounded_turn(
            ticket,
            suggestion.grounding_status,
            suggestion.gate,
        ) and (
            suggestion.completion is None
            or bool(suggestion.completion.get("complete"))
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
        return self._next_pending_turn(conversation.id, exclude=turn.id)

    def _blocked_by_earlier_turn(
        self,
        turn: ConversationTurn,
        now: datetime,
    ) -> bool:
        """True when another turn of this conversation still owns the floor.

        Turns of one conversation run one at a time: either an earlier turn is
        still queued with a live lease, or a turn is actively RUNNING. A turn
        whose lease already expired does not block, so a dead worker cannot
        stall the conversation.
        """
        blocker = self.session.scalar(
            select(ConversationTurn.id)
            .where(
                ConversationTurn.conversation_id == turn.conversation_id,
                ConversationTurn.id != turn.id,
                ConversationTurn.lease_expires_at.is_not(None),
                ConversationTurn.lease_expires_at > now,
                or_(
                    ConversationTurn.sequence < turn.sequence,
                    ConversationTurn.status == TurnStatus.RUNNING.value,
                ),
            )
            .limit(1)
        )
        return blocker is not None

    def _next_pending_turn(
        self,
        conversation_id: UUID,
        *,
        exclude: UUID,
    ) -> UUID | None:
        next_turn_id = self.session.scalar(
            select(ConversationTurn.id)
            .where(
                ConversationTurn.conversation_id == conversation_id,
                ConversationTurn.id != exclude,
                ConversationTurn.status == TurnStatus.PENDING.value,
            )
            .order_by(ConversationTurn.sequence.asc())
            .limit(1)
        )
        return next_turn_id

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
        self.session.refresh(turn)
        if parse_turn_status(turn.status) is TurnStatus.CANCELLED:
            # A human owns the conversation now; a failure notice would be
            # noise talking over them.
            self.session.rollback()
            return
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
            turn_id=turn.id,
        )
        turn.assistant_message_id = message.id
        conversation.version += 1
        self.session.commit()


# A single dispatch may have to work through a conversation's queue; the bound
# keeps a pathological backlog from holding one worker forever.
MAX_QUEUED_TURNS_PER_DISPATCH = 10


# A deadlock with a human takeover kills one transaction; retrying the turn in
# a fresh one is cheap, while leaving it RUNNING would stall the buyer until the
# lease reclaim job notices.
MAX_TURN_DEADLOCK_RETRIES = 2
TURN_DEADLOCK_BACKOFF_SECONDS = 0.05


def _release_turn_lease(session: Session, turn_id: UUID) -> None:
    """Let ``process`` resume a turn whose transaction was rolled back."""
    turn = session.get(ConversationTurn, turn_id)
    if turn is None:
        return
    if parse_turn_status(turn.status) not in {
        TurnStatus.PENDING,
        TurnStatus.RUNNING,
    }:
        return
    turn.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()


def process_conversation_turn(turn_id: UUID, correlation_id: str) -> None:
    with SessionLocal() as session:
        orchestrator = ConversationTurnOrchestrator(session)
        current: UUID | None = turn_id
        deadlock_retries = 0
        for _ in range(MAX_QUEUED_TURNS_PER_DISPATCH):
            if current is None:
                return
            turn_under_dispatch = current
            try:
                current = orchestrator.process(
                    turn_under_dispatch,
                    correlation_id=correlation_id,
                )
            except OperationalError as exc:
                session.rollback()
                if not is_deadlock_error(exc):
                    raise
                deadlock_retries += 1
                if deadlock_retries > MAX_TURN_DEADLOCK_RETRIES:
                    # Hand the turn to the lease reclaim job instead of
                    # spinning: it is already terminal or retryable there.
                    _release_turn_lease(session, turn_under_dispatch)
                    logger.exception(
                        "conversation turn %s kept deadlocking; "
                        "left it to the reclaim job",
                        turn_under_dispatch,
                    )
                    return
                logger.warning(
                    "conversation turn %s lost a deadlock with a human action; "
                    "retrying (attempt %s/%s)",
                    turn_under_dispatch,
                    deadlock_retries,
                    MAX_TURN_DEADLOCK_RETRIES,
                )
                sleep(TURN_DEADLOCK_BACKOFF_SECONDS * deadlock_retries)
                _release_turn_lease(session, turn_under_dispatch)


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
            current = session.get(ConversationTurn, turn_id)
            if current is not None and current.status == "PENDING":
                # Another turn of this conversation is still running; say so
                # instead of ending the stream with no explanation.
                emit(
                    {
                        "type": "status",
                        "turn_id": str(turn_id),
                        "stage": "已排队，等待上一轮完成",
                    }
                )
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
    gate: dict[str, object] | None,
) -> bool:
    # Completing a ticket is an irreversible claim that the question is
    # settled. The gate must have cleared the answer for unattended sending;
    # a missing gate (old code path, failed evaluation) fails closed.
    return (
        grounding_status == "GROUNDED"
        and gate is not None
        and gate.get("decision") == "AUTO_SEND"
        and not ticket.needs_human
        and ticket.risk_level not in {"R2", "R3"}
    )

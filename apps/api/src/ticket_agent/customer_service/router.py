import asyncio
import json
import queue
import threading
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, status
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from ticket_agent.api.dependencies import Actor, DbSession, correlation_id
from ticket_agent.customer_service.business_context import (
    CustomerBusinessActionService,
    CustomerBusinessContextService,
)
from ticket_agent.customer_service.models import (
    CustomerConversation,
    CustomerServiceNotification,
)
from ticket_agent.customer_service.reply_optimization import (
    CustomerReplyOptimizationService,
)
from ticket_agent.customer_service.schemas import (
    AddressChangeCreate,
    AgentHeartbeat,
    AgentPresenceList,
    AgentPresenceView,
    AssignmentQueue,
    AssignmentRunResult,
    ConversationReassignRequest,
    ConversationTurnEventList,
    ConversationTurnEventView,
    CustomerBusinessActionView,
    CustomerBusinessContextView,
    CustomerConversationCreate,
    CustomerConversationList,
    CustomerConversationView,
    CustomerManualReplyCreate,
    CustomerMessageCreate,
    CustomerReplyOptimizationCreate,
    CustomerReplyOptimizationView,
    CustomerReplySuggestionView,
    CustomerServiceAlertList,
    CustomerServiceHistoryMetrics,
    CustomerServiceMetrics,
    CustomerServiceNotificationList,
    CustomerServiceNotificationView,
    CustomerTakeoverRequest,
    CustomerValueMetrics,
    PresenceReclaimResult,
    SlaEscalationResult,
    TurnReclaimResult,
)
from ticket_agent.customer_service.service import CustomerConversationService
from ticket_agent.customer_service.suggestions import (
    CustomerReplySuggestionService,
)
from ticket_agent.customer_service.turn_events import reclaim_stuck_turns
from ticket_agent.customer_service.turns import (
    process_conversation_turn,
    process_conversation_turn_stream,
)
from ticket_agent.customer_service.value_metrics import (
    CustomerValueMetricsService,
)
from ticket_agent.identity.dependencies import (
    ensure_business_unit_access,
    ensure_metrics_viewer,
    ensure_service_admin,
    ensure_service_chat,
    ensure_service_workbench,
    ensure_sync_batch_operator,
    resolve_business_unit,
)
from ticket_agent.shared.db import SessionLocal
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.rate_limit import rate_limited
from ticket_agent.shared.settings import get_settings

router = APIRouter()

_STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


class _DurableEventStream(StreamingResponse):
    """SSE response that lets the turn finish if the browser disconnects.

    Starlette's default implementation races the stream against a disconnect
    listener and cancels the generator. A conversation turn owns server-side
    work that must still be persisted, so this response keeps consuming the
    event queue until the worker reports completion.
    """

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        del scope, receive
        try:
            await self.stream_response(send)
        except OSError:
            return
        if self.background is not None:
            await self.background()


def _sse_event(event: str, payload: dict[str, object]) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {data}\n\n"


def _conversation_for_access(
    service: CustomerConversationService,
    conversation_id: UUID,
    principal: Actor,
) -> CustomerConversation:
    conversation = service.get(conversation_id)
    ensure_business_unit_access(principal, conversation.business_unit_id)
    return conversation


def _notification_for_access(
    service: CustomerConversationService,
    notification_id: UUID,
    principal: Actor,
) -> CustomerServiceNotification:
    notification = service.get_notification(notification_id)
    ensure_business_unit_access(principal, notification.business_unit_id)
    return notification


@router.get(
    "/customer-service/metrics",
    response_model=CustomerServiceMetrics,
)
def get_customer_service_metrics(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> CustomerServiceMetrics:
    ensure_service_admin(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    return CustomerConversationService(db).metrics(
        business_unit_id=business_unit_id
    )


@router.get(
    "/customer-service/value-metrics",
    response_model=CustomerValueMetrics,
)
def get_customer_value_metrics(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> CustomerValueMetrics:
    ensure_metrics_viewer(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    return CustomerValueMetrics(
        **CustomerValueMetricsService(db).summary(
            business_unit_id=business_unit_id,
            days=days,
        )
    )


@router.get(
    "/customer-service/metrics/history",
    response_model=CustomerServiceHistoryMetrics,
)
def get_customer_service_history_metrics(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> CustomerServiceHistoryMetrics:
    ensure_service_admin(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    return CustomerConversationService(db).history_metrics(
        business_unit_id=business_unit_id,
        days=days,
    )


@router.post("/customer-service/presence/heartbeat", response_model=AgentPresenceView)
def heartbeat_agent(
    payload: AgentHeartbeat,
    db: DbSession,
    principal: Actor,
) -> AgentPresenceView:
    ensure_service_workbench(principal)
    ensure_business_unit_access(principal, payload.business_unit_id)
    service = CustomerConversationService(db)
    presence = service.heartbeat(
        payload,
        agent_id=principal.actor_id,
        actor_role=principal.role,
    )
    cutoff = datetime.now(UTC) - timedelta(seconds=60)
    return AgentPresenceView(
        agent_id=presence.agent_id,
        display_name=presence.display_name,
        status=presence.status,
        current_conversation_id=presence.current_conversation_id,
        business_unit_id=presence.business_unit_id,
        actor_role=presence.actor_role,
        skills=presence.skills_json,
        risk_clearance=presence.risk_clearance,
        max_conversations=presence.max_conversations,
        auto_assign_enabled=presence.auto_assign_enabled,
        last_seen_at=presence.last_seen_at,
        online=(
            (
                presence.last_seen_at
                if presence.last_seen_at.tzinfo
                else presence.last_seen_at.replace(tzinfo=UTC)
            )
            >= cutoff
            and presence.status == "ONLINE"
        ),
    )


@router.get("/customer-service/presence", response_model=AgentPresenceList)
def list_agent_presence(db: DbSession, principal: Actor) -> AgentPresenceList:
    ensure_service_workbench(principal)
    business_unit_id = resolve_business_unit(principal)
    return CustomerConversationService(db).presence(business_unit_id)


@router.get(
    "/customer-service/assignment-queue",
    response_model=AssignmentQueue,
)
def get_assignment_queue(db: DbSession, principal: Actor) -> AssignmentQueue:
    ensure_service_workbench(principal)
    business_unit_id = resolve_business_unit(principal)
    return CustomerConversationService(db).assignment_queue(business_unit_id)


@router.post(
    "/customer-service/presence/reclaim-offline",
    response_model=PresenceReclaimResult,
)
def reclaim_offline_presence(
    db: DbSession,
    principal: Actor,
) -> PresenceReclaimResult:
    ensure_service_admin(principal)
    business_unit_id = resolve_business_unit(principal)
    return PresenceReclaimResult(
        reclaimed_count=CustomerConversationService(
            db
        ).reclaim_offline_conversations(
            business_unit_id=business_unit_id
        )
    )


@router.post(
    "/customer-service/assignment-queue/auto-assign",
    response_model=AssignmentRunResult,
)
def auto_assign_customer_conversations(
    db: DbSession,
    principal: Actor,
) -> AssignmentRunResult:
    ensure_service_admin(principal)
    business_unit_id = resolve_business_unit(principal)
    return CustomerConversationService(db).auto_assign(business_unit_id)


@router.get(
    "/customer-service/alerts",
    response_model=CustomerServiceAlertList,
)
def list_customer_service_alerts(
    db: DbSession,
    principal: Actor,
) -> CustomerServiceAlertList:
    ensure_service_admin(principal)
    business_unit_id = resolve_business_unit(principal)
    return CustomerConversationService(db).alerts(
        business_unit_id=business_unit_id
    )


@router.post(
    "/customer-service/alerts/escalate",
    response_model=SlaEscalationResult,
)
def escalate_customer_service_sla(
    db: DbSession,
    principal: Actor,
) -> SlaEscalationResult:
    ensure_service_admin(principal)
    business_unit_id = resolve_business_unit(principal)
    return SlaEscalationResult(
        escalated_count=CustomerConversationService(
            db
        ).escalate_overdue_conversations(
            business_unit_id=business_unit_id
        )
    )


@router.post("/customer-service/notifications/sync")
def sync_customer_service_notifications(
    db: DbSession,
    principal: Actor,
) -> dict[str, int]:
    ensure_sync_batch_operator(principal)
    business_unit_id = resolve_business_unit(principal)
    return {
        "created_count": CustomerConversationService(
            db
        ).sync_supervisor_notifications(business_unit_id)
    }


@router.post(
    "/customer-service/turns/reclaim",
    response_model=TurnReclaimResult,
)
def reclaim_customer_conversation_turns(
    background_tasks: BackgroundTasks,
    db: DbSession,
    principal: Actor,
) -> TurnReclaimResult:
    """Recover turns whose worker lease expired.

    Runs every 30 seconds from Celery beat; this entry point lets an operator
    trigger the same job on demand.
    """
    ensure_sync_batch_operator(principal)
    turn_ids = reclaim_stuck_turns(
        db,
        limit=get_settings().conversation_turn_reclaim_batch_size,
    )
    for turn_id in turn_ids:
        background_tasks.add_task(
            process_conversation_turn,
            turn_id,
            f"turn-reclaim:{turn_id}",
        )
    return TurnReclaimResult(
        reclaimed=len(turn_ids),
        redispatched=len(turn_ids),
    )


@router.get(
    "/customer-service/notifications",
    response_model=CustomerServiceNotificationList,
)
def list_customer_service_notifications(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> CustomerServiceNotificationList:
    ensure_service_admin(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    return CustomerConversationService(db).notifications(
        business_unit_id=business_unit_id
    )


@router.post(
    "/customer-service/notifications/{notification_id}/acknowledge",
    response_model=CustomerServiceNotificationView,
)
def acknowledge_customer_service_notification(
    notification_id: UUID,
    db: DbSession,
    principal: Actor,
) -> CustomerServiceNotificationView:
    ensure_service_admin(principal)
    service = CustomerConversationService(db)
    _notification_for_access(service, notification_id, principal)
    return service.notification_view(
        service.acknowledge_notification(
            notification_id,
            actor_id=principal.actor_id,
        )
    )


@router.post(
    "/customer-service/conversations/{conversation_id}/reassign",
    response_model=CustomerConversationView,
)
def reassign_customer_conversation(
    conversation_id: UUID,
    payload: ConversationReassignRequest,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> CustomerConversationView:
    ensure_service_admin(principal)
    service = CustomerConversationService(db)
    _conversation_for_access(service, conversation_id, principal)
    return service.view(
        service.reassign(
            conversation_id,
            payload,
            supervisor_id=principal.actor_id,
            correlation_id=correlation_id(request),
        )
    )


@router.get("/customer-service/conversations/{conversation_id}/events")
def stream_customer_conversation(
    conversation_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> StreamingResponse:
    ensure_service_chat(principal)
    _conversation_for_access(
        CustomerConversationService(db),
        conversation_id,
        principal,
    )

    async def events() -> AsyncIterator[str]:
        signature: tuple[object, ...] | None = None
        while not await request.is_disconnected():
            with SessionLocal() as session:
                service = CustomerConversationService(session)
                conversation = service.get(conversation_id)
                messages = service.messages(conversation.id)
                current_turn = service.view(conversation).current_turn
                next_signature = (
                    conversation.version,
                    conversation.current_ticket_id,
                    conversation.assigned_agent_id,
                    len(messages),
                    messages[-1].created_at if messages else None,
                    current_turn.status if current_turn else None,
                    current_turn.completed_at if current_turn else None,
                )
                if next_signature != signature:
                    signature = next_signature
                    payload = service.view(conversation).model_dump(mode="json")
                    data = json.dumps(payload, ensure_ascii=False)
                    yield f"event: conversation\ndata: {data}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/customer-service/conversations",
    response_model=CustomerConversationView,
    status_code=status.HTTP_201_CREATED,
)
def create_customer_conversation(
    payload: CustomerConversationCreate,
    db: DbSession,
    principal: Actor,
) -> CustomerConversationView:
    ensure_service_chat(principal)
    ensure_business_unit_access(principal, payload.business_unit_id)
    service = CustomerConversationService(db)
    return service.view(service.create(payload))


@router.get(
    "/customer-service/conversations",
    response_model=CustomerConversationList,
)
def list_customer_conversations(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> CustomerConversationList:
    ensure_service_chat(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    return CustomerConversationService(db).list(business_unit_id)


@router.post(
    "/customer-service/test-cleanup",
    response_model=dict[str, int],
)
def cleanup_test_customer_conversations(
    db: DbSession,
    principal: Actor,
    business_unit_id: str = Query(min_length=1),
    requester_prefix: str = Query(min_length=1, max_length=100),
) -> dict[str, int]:
    if get_settings().app_env not in {"development", "test"}:
        raise ApiProblem(
            status_code=403,
            code="TEST_CLEANUP_DISABLED",
            title="Test cleanup is disabled",
            detail=(
                "Test conversation cleanup is only available in "
                "development or test."
            ),
        )
    if principal.role != "admin":
        raise ApiProblem(
            status_code=403,
            code="FORBIDDEN",
            title="Admin role required",
            detail="Only administrators can clean up test conversations.",
        )
    archived = CustomerConversationService(db).archive_test_conversations(
        business_unit_id=resolve_business_unit(principal, business_unit_id),
        requester_prefix=requester_prefix,
    )
    return {"archived": archived}


@router.post(
    "/customer-service/conversations/{conversation_id}/archive-test-data",
    response_model=CustomerConversationView,
)
def archive_test_customer_conversation(
    conversation_id: UUID,
    db: DbSession,
    principal: Actor,
) -> CustomerConversationView:
    if get_settings().app_env not in {"development", "test"}:
        raise ApiProblem(
            status_code=403,
            code="TEST_CLEANUP_DISABLED",
            title="Test cleanup is disabled",
            detail=(
                "Test conversation cleanup is only available in "
                "development or test."
            ),
        )
    if principal.role != "admin":
        raise ApiProblem(
            status_code=403,
            code="FORBIDDEN",
            title="Admin role required",
            detail="Only administrators can clean up test conversations.",
        )
    service = CustomerConversationService(db)
    _conversation_for_access(service, conversation_id, principal)
    return service.view(
        service.archive_test_conversation(conversation_id)
    )


@router.get(
    "/customer-service/conversations/{conversation_id}",
    response_model=CustomerConversationView,
)
def get_customer_conversation(
    conversation_id: UUID,
    db: DbSession,
    principal: Actor,
) -> CustomerConversationView:
    ensure_service_chat(principal)
    service = CustomerConversationService(db)
    conversation = _conversation_for_access(
        service, conversation_id, principal
    )
    return service.view(conversation)


@router.get(
    "/customer-service/conversations/{conversation_id}/turns/{turn_id}/events",
    response_model=ConversationTurnEventList,
)
def list_customer_conversation_turn_events(
    conversation_id: UUID,
    turn_id: UUID,
    db: DbSession,
    principal: Actor,
) -> ConversationTurnEventList:
    """Show what one turn actually did, step by step.

    The conversation row only stores the latest turn state; this endpoint is
    the operator-facing view of the append-only turn event log.
    """
    ensure_service_chat(principal)
    service = CustomerConversationService(db)
    _conversation_for_access(service, conversation_id, principal)
    service.get_turn(conversation_id, turn_id)
    return ConversationTurnEventList(
        conversation_id=conversation_id,
        turn_id=turn_id,
        events=[
            ConversationTurnEventView(
                id=event.id,
                turn_id=event.turn_id,
                conversation_id=event.conversation_id,
                sequence=event.sequence,
                event_type=event.event_type,
                status=event.status,
                stage_label=event.stage_label,
                actor_type=event.actor_type,
                actor_id=event.actor_id,
                correlation_id=event.correlation_id,
                payload=event.payload_json,
                created_at=event.created_at,
            )
            for event in service.turn_events(turn_id)
        ],
    )


@router.get(
    "/customer-service/conversations/{conversation_id}/business-context",
    response_model=CustomerBusinessContextView,
)
def get_customer_business_context(
    conversation_id: UUID,
    db: DbSession,
    principal: Actor,
    order_id: Annotated[str | None, Query(max_length=128)] = None,
) -> CustomerBusinessContextView:
    ensure_service_chat(principal)
    service = CustomerConversationService(db)
    conversation = service.get(conversation_id)
    ensure_business_unit_access(
        principal,
        conversation.business_unit_id,
    )
    return CustomerBusinessContextService().resolve(
        conversation,
        service.messages(conversation.id),
        order_id=order_id,
    )


@router.post(
    "/customer-service/conversations/{conversation_id}/business-actions/address-change",
    response_model=CustomerBusinessActionView,
)
def request_customer_address_change(
    conversation_id: UUID,
    payload: AddressChangeCreate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> CustomerBusinessActionView:
    ensure_service_chat(principal)
    service = CustomerConversationService(db)
    conversation = service.get(conversation_id)
    ensure_business_unit_access(
        principal,
        conversation.business_unit_id,
    )
    return CustomerBusinessActionService(db).request_address_change(
        conversation,
        service.messages(conversation.id),
        payload,
        actor_id=principal.actor_id,
        correlation_id=correlation_id(request),
    )


@router.post(
    "/customer-service/conversations/{conversation_id}/messages",
    response_model=CustomerConversationView,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limited())],
)
def add_customer_message(
    conversation_id: UUID,
    payload: CustomerMessageCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: DbSession,
    principal: Actor,
) -> CustomerConversationView:
    ensure_service_chat(principal)
    service = CustomerConversationService(db)
    _conversation_for_access(service, conversation_id, principal)
    conversation, turn_id = service.append_buyer_message(
        conversation_id,
        payload,
        principal=principal,
        correlation_id=correlation_id(request),
    )
    if turn_id is not None:
        background_tasks.add_task(
            process_conversation_turn,
            turn_id,
            correlation_id(request),
        )
    return service.view(conversation)


@router.post(
    "/customer-service/conversations/{conversation_id}/messages/stream",
    dependencies=[Depends(rate_limited())],
)
def stream_customer_message(
    conversation_id: UUID,
    payload: CustomerMessageCreate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> StreamingResponse:
    ensure_service_chat(principal)
    service = CustomerConversationService(db)
    _conversation_for_access(service, conversation_id, principal)
    conversation, turn_id = service.append_buyer_message(
        conversation_id,
        payload,
        principal=principal,
        correlation_id=correlation_id(request),
    )
    initial_view = service.view(conversation).model_dump(mode="json")
    # Release the request's read transaction before the worker writes in its
    # own session (SQLite tests would otherwise block on a shared lock).
    db.close()
    events: queue.Queue[dict[str, object]] = queue.Queue()
    worker: threading.Thread | None = None
    if turn_id is not None:
        worker = threading.Thread(
            target=process_conversation_turn_stream,
            args=(
                turn_id,
                correlation_id(request),
                events.put,
            ),
            daemon=True,
            name=f"conversation-turn-{turn_id}",
        )
        worker.start()

    async def event_stream() -> AsyncIterator[str]:
        yield _sse_event(
            "start",
            {
                "type": "start",
                "turn_id": str(turn_id) if turn_id else None,
                "conversation": initial_view,
            },
        )
        if turn_id is None or worker is None:
            yield _sse_event(
                "done",
                {
                    "type": "done",
                    "turn_id": None,
                    "conversation": initial_view,
                },
            )
            return
        while True:
            try:
                event = await asyncio.to_thread(events.get, True, 0.5)
            except queue.Empty:
                # Starlette cancels this generator on client disconnect;
                # keep-alives just stop proxy idle timeouts meanwhile.
                yield ": keep-alive\n\n"
                continue
            event_type = str(event.get("type", "message"))
            yield _sse_event(event_type, event)
            if event_type in {"done", "error"}:
                return

    return _DurableEventStream(
        event_stream(),
        media_type="text/event-stream",
        headers=_STREAM_HEADERS,
    )


@router.post(
    "/customer-service/conversations/{conversation_id}/takeover",
    response_model=CustomerConversationView,
)
def take_over_customer_conversation(
    conversation_id: UUID,
    payload: CustomerTakeoverRequest,
    db: DbSession,
    principal: Actor,
) -> CustomerConversationView:
    ensure_service_workbench(principal)
    service = CustomerConversationService(db)
    _conversation_for_access(service, conversation_id, principal)
    return service.view(
        service.takeover(
            conversation_id,
            expected_version=payload.expected_version,
            agent_id=principal.actor_id,
        )
    )


@router.post(
    "/customer-service/conversations/{conversation_id}/release",
    response_model=CustomerConversationView,
)
def release_customer_conversation(
    conversation_id: UUID,
    db: DbSession,
    principal: Actor,
) -> CustomerConversationView:
    ensure_service_workbench(principal)
    service = CustomerConversationService(db)
    _conversation_for_access(service, conversation_id, principal)
    return service.view(
        service.release(conversation_id, agent_id=principal.actor_id)
    )


@router.post(
    "/customer-service/conversations/{conversation_id}/manual-replies",
    response_model=CustomerConversationView,
    status_code=status.HTTP_201_CREATED,
)
def send_manual_customer_reply(
    conversation_id: UUID,
    payload: CustomerManualReplyCreate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> CustomerConversationView:
    ensure_service_workbench(principal)
    service = CustomerConversationService(db)
    _conversation_for_access(service, conversation_id, principal)
    return service.view(
        service.send_manual_reply(
            conversation_id,
            payload,
            agent_id=principal.actor_id,
            correlation_id=correlation_id(request),
        )
    )


@router.post(
    "/customer-service/conversations/{conversation_id}/reply-suggestions",
    response_model=CustomerReplySuggestionView,
    dependencies=[Depends(rate_limited())],
)
def generate_customer_reply_suggestion(
    conversation_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> CustomerReplySuggestionView:
    ensure_service_workbench(principal)
    _conversation_for_access(
        CustomerConversationService(db),
        conversation_id,
        principal,
    )
    return CustomerReplySuggestionService(db).generate(
        conversation_id,
        agent_id=principal.actor_id,
        correlation_id=correlation_id(request),
    )


@router.post(
    "/customer-service/conversations/{conversation_id}/reply-optimizations",
    response_model=CustomerReplyOptimizationView,
    dependencies=[Depends(rate_limited())],
)
def optimize_customer_reply(
    conversation_id: UUID,
    payload: CustomerReplyOptimizationCreate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> CustomerReplyOptimizationView:
    ensure_service_workbench(principal)
    _conversation_for_access(
        CustomerConversationService(db),
        conversation_id,
        principal,
    )
    return CustomerReplyOptimizationService(db).optimize(
        conversation_id,
        payload,
        agent_id=principal.actor_id,
        correlation_id=correlation_id(request),
    )

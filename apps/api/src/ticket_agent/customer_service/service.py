import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import Session

from ticket_agent.audit.service import record_audit
from ticket_agent.business_entries.service import service_entry_employee_ids
from ticket_agent.classification.conversation_signals import (
    SmallTalkKind,
    classify_small_talk,
    repository_name,
)
from ticket_agent.customer_service.context import (
    MemorySnapshot,
    assemble_context,
    record_memory_turn,
)
from ticket_agent.customer_service.domain import (
    TERMINAL_TURN_STATUSES,
    TurnStatus,
    parse_turn_status,
)
from ticket_agent.customer_service.gate import GateContext, evaluate_gate
from ticket_agent.customer_service.handoffs import (
    create_handoff,
    latest_human_message,
    latest_turn,
)
from ticket_agent.customer_service.models import (
    AgentPresence,
    ConversationHandoff,
    ConversationMemory,
    ConversationTurn,
    ConversationTurnEvent,
    CustomerConversation,
    CustomerMessage,
    CustomerServiceNotification,
)
from ticket_agent.customer_service.schemas import (
    AgentHeartbeat,
    AgentPresenceList,
    AgentPresenceView,
    AssignmentQueue,
    AssignmentQueueItem,
    AssignmentResultItem,
    AssignmentRunResult,
    ConversationHandoffList,
    ConversationHandoffView,
    ConversationReassignRequest,
    ConversationTurnDetailView,
    ConversationTurnList,
    ConversationTurnView,
    CustomerConversationCreate,
    CustomerConversationList,
    CustomerConversationView,
    CustomerDailyMetric,
    CustomerManualReplyCreate,
    CustomerMessageCreate,
    CustomerMessageView,
    CustomerServiceAlertItem,
    CustomerServiceAlertList,
    CustomerServiceHistoryMetrics,
    CustomerServiceMetrics,
    CustomerServiceNotificationList,
    CustomerServiceNotificationView,
    OperationalTurnList,
    OperationalTurnView,
    RuntimeGapItem,
    RuntimeHealthView,
)
from ticket_agent.customer_service.turn_events import (
    list_turn_events,
    new_lease,
    record_turn_event,
    transition_turn,
)
from ticket_agent.digital_employees.models import (
    DigitalEmployee,
    DigitalEmployeeRouteDecision,
)
from ticket_agent.digital_employees.router_service import (
    DigitalEmployeeRouter,
    explicit_employee_request,
)
from ticket_agent.identity.models import Principal
from ticket_agent.knowledge.models import KnowledgeGapOccurrence
from ticket_agent.shared.db import run_with_deadlock_retry
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import get_settings
from ticket_agent.tickets.domain import TicketStatus, WorkflowState
from ticket_agent.tickets.models import Ticket, WorkflowTransition
from ticket_agent.tickets.schemas import RequesterInput, SourceInput, TicketCreate
from ticket_agent.tickets.service import TicketService
from ticket_agent.tickets.transitions import transition_ticket

logger = logging.getLogger(__name__)

# Ticket states a human takeover may move to TAKEN_OVER. The list mirrors
# ALLOWED_WORKFLOW_TRANSITIONS; a completed ticket stays completed because the
# workflow has no edge back for an automated caller.
_HUMAN_TAKEOVER_TICKET_STATES = frozenset(
    {
        WorkflowState.RECEIVED,
        WorkflowState.CLASSIFYING,
        WorkflowState.RISK_EVALUATED,
        WorkflowState.ROUTING,
        WorkflowState.DRAFTING,
        WorkflowState.PENDING_REVIEW,
        WorkflowState.SYNCING,
        WorkflowState.NEEDS_HUMAN,
        WorkflowState.FAILED_RETRYABLE,
    }
)



@dataclass(frozen=True)
class BuyerMessageResult:
    """Outcome of one inbound buyer message.

    ``replayed`` means the caller reused a ``client_message_id`` that already
    produced a turn: no message, turn or audit row was written this time.
    """

    conversation: CustomerConversation
    turn_id: UUID | None
    replayed: bool = False


class CustomerConversationService:
    MAX_AGENT_CONVERSATIONS = 5
    SLA_SECONDS = {"P0": 60, "P1": 180, "P2": 300, "P3": 600}
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, payload: CustomerConversationCreate) -> CustomerConversation:
        # An explicitly requested employee is a deliberate assignment: the
        # entry router must not silently take the conversation back later.
        explicit_employee = payload.employee_id is not None
        conversation = CustomerConversation(
            business_unit_id=payload.business_unit_id,
            service_entry_id=payload.service_entry_id,
            employee_id=payload.employee_id,
            employee_source="MANUAL" if explicit_employee else "ROUTER",
            employee_locked_at=datetime.now(UTC) if explicit_employee else None,
            requester_ref=payload.requester_ref,
            category_name=payload.category_name,
            category_profile_id=payload.category_profile_id,
            channel=payload.channel,
            status="ACTIVE",
        )
        self.session.add(conversation)
        self.session.commit()
        self.session.refresh(conversation)
        return conversation

    def heartbeat(
        self,
        payload: AgentHeartbeat,
        *,
        agent_id: str,
        actor_role: str = "agent",
    ) -> AgentPresence:
        presence = self.session.scalar(
            select(AgentPresence).where(AgentPresence.agent_id == agent_id)
        )
        if presence is None:
            presence = AgentPresence(
                agent_id=agent_id,
                display_name=payload.display_name,
            )
            self.session.add(presence)
        presence.display_name = payload.display_name
        presence.business_unit_id = payload.business_unit_id
        presence.status = payload.status
        presence.current_conversation_id = payload.current_conversation_id
        presence.actor_role = actor_role
        presence.skills_json = (
            payload.skills
            or [
                "ecommerce_presales",
                "ecommerce_aftersales",
                "logistics",
            ]
        )
        presence.risk_clearance = payload.risk_clearance or (
            "R3" if actor_role in {"supervisor", "admin"} else "R2"
        )
        presence.max_conversations = payload.max_conversations or 5
        presence.auto_assign_enabled = payload.auto_assign_enabled
        presence.last_seen_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(presence)
        return presence

    def presence(
        self,
        business_unit_id: str | None = None,
    ) -> AgentPresenceList:
        cutoff = datetime.now(UTC) - timedelta(seconds=60)
        statement = select(AgentPresence).order_by(
            AgentPresence.last_seen_at.desc()
        )
        if business_unit_id:
            statement = statement.where(
                AgentPresence.business_unit_id == business_unit_id
            )
        items = list(self.session.scalars(statement).all())
        views = [
            AgentPresenceView(
                agent_id=item.agent_id,
                display_name=item.display_name,
                status=item.status,
                current_conversation_id=item.current_conversation_id,
                business_unit_id=item.business_unit_id,
                actor_role=item.actor_role,
                skills=item.skills_json,
                risk_clearance=item.risk_clearance,
                max_conversations=item.max_conversations,
                auto_assign_enabled=item.auto_assign_enabled,
                last_seen_at=item.last_seen_at,
                online=_as_utc(item.last_seen_at) >= cutoff
                and item.status == "ONLINE",
            )
            for item in items
        ]
        return AgentPresenceList(
            items=views,
            online_count=sum(item.online for item in views),
        )

    def assignment_queue(
        self,
        business_unit_id: str | None = None,
    ) -> AssignmentQueue:
        now = datetime.now(UTC)
        statement = (
            select(CustomerConversation, Ticket)
            .outerjoin(Ticket, Ticket.id == CustomerConversation.current_ticket_id)
            .where(
                CustomerConversation.assigned_agent_id.is_(None),
                CustomerConversation.status == "ACTIVE",
                Ticket.workflow_state.in_(
                    {
                        WorkflowState.PENDING_REVIEW,
                        WorkflowState.NEEDS_HUMAN,
                    }
                ),
            )
        )
        if business_unit_id:
            statement = statement.where(
                CustomerConversation.business_unit_id == business_unit_id
            )
        rows = self.session.execute(statement).all()
        rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        items = [
            AssignmentQueueItem(
                conversation_id=conversation.id,
                requester_ref=conversation.requester_ref,
                current_ticket_id=conversation.current_ticket_id,
                priority=ticket.priority if ticket and ticket.priority else "P3",
                risk_level=ticket.risk_level if ticket else None,
                waiting_seconds=max(
                    0,
                    round((now - _as_utc(conversation.created_at)).total_seconds()),
                ),
                created_at=conversation.created_at,
            )
            for conversation, ticket in rows
        ]
        items.sort(
            key=lambda item: (rank.get(item.priority, 9), -item.waiting_seconds)
        )
        return AssignmentQueue(items=items, total=len(items))

    def reclaim_offline_conversations(
        self,
        *,
        business_unit_id: str | None = None,
        stale_after_seconds: int = 90,
    ) -> int:
        cutoff = datetime.now(UTC) - timedelta(seconds=stale_after_seconds)
        presence_statement = select(AgentPresence)
        if business_unit_id:
            presence_statement = presence_statement.where(
                AgentPresence.business_unit_id == business_unit_id
            )
        presences = list(
            self.session.scalars(presence_statement).all()
        )
        offline_agent_ids = {
            presence.agent_id
            for presence in presences
            if presence.status != "ONLINE"
            or _as_utc(presence.last_seen_at) < cutoff
        }
        for presence in presences:
            if presence.agent_id in offline_agent_ids:
                presence.status = "OFFLINE"
                presence.current_conversation_id = None
        if not offline_agent_ids:
            self.session.commit()
            return 0
        conversation_statement = (
            select(CustomerConversation)
            .where(
                CustomerConversation.assigned_agent_id.in_(offline_agent_ids),
                CustomerConversation.status == "ACTIVE",
            )
            .with_for_update()
        )
        if business_unit_id:
            conversation_statement = conversation_statement.where(
                CustomerConversation.business_unit_id == business_unit_id
            )
        conversations = list(
            self.session.scalars(conversation_statement).all()
        )
        for conversation in conversations:
            conversation.assigned_agent_id = None
            conversation.assigned_at = None
            conversation.version += 1
            conversation.status = "ACTIVE"
        self.session.commit()
        return len(conversations)

    def auto_assign(
        self,
        business_unit_id: str | None = None,
    ) -> AssignmentRunResult:
        cutoff = datetime.now(UTC) - timedelta(seconds=60)
        online = [
            item
            for item in self.presence(business_unit_id).items
            if item.online and _as_utc(item.last_seen_at) >= cutoff
            and item.auto_assign_enabled
            and (
                business_unit_id is None
                or item.business_unit_id == business_unit_id
            )
        ]
        if not online:
            return AssignmentRunResult(
                assignments=[],
                assigned_count=0,
                unassigned_count=self.assignment_queue(business_unit_id).total,
            )
        load_statement = (
            select(
                CustomerConversation.assigned_agent_id,
                func.count(CustomerConversation.id),
            )
            .where(
                CustomerConversation.assigned_agent_id.in_(
                    [agent.agent_id for agent in online]
                ),
                CustomerConversation.status == "ACTIVE",
            )
            .group_by(CustomerConversation.assigned_agent_id)
        )
        if business_unit_id:
            load_statement = load_statement.where(
                CustomerConversation.business_unit_id == business_unit_id
            )
        load_rows = self.session.execute(load_statement).all()
        loads = {agent_id: int(count) for agent_id, count in load_rows}
        queue = self.assignment_queue(business_unit_id)
        assignments: list[AssignmentResultItem] = []
        for item in queue.items:
            conversation = self.session.scalar(
                select(CustomerConversation)
                .where(CustomerConversation.id == item.conversation_id)
                .with_for_update()
            )
            if conversation is None or conversation.assigned_agent_id is not None:
                continue
            ticket = (
                self.session.get(Ticket, conversation.current_ticket_id)
                if conversation.current_ticket_id
                else None
            )
            risk_level = ticket.risk_level if ticket else "R1"
            required_skill = _required_skill(ticket)
            candidate_details: list[dict[str, Any]] = []
            for candidate in online:
                candidate_load = loads.get(candidate.agent_id, 0)
                excluded_reasons: list[str] = []
                if candidate_load >= candidate.max_conversations:
                    excluded_reasons.append(
                        f"并发已满 {candidate_load}/"
                        f"{candidate.max_conversations}"
                    )
                if (
                    _risk_rank(candidate.risk_clearance)
                    < _risk_rank(risk_level)
                ):
                    excluded_reasons.append(
                        f"风险权限 {candidate.risk_clearance} "
                        f"低于工单 {risk_level}"
                    )
                if (
                    candidate.skills
                    and required_skill is not None
                    and required_skill not in candidate.skills
                ):
                    excluded_reasons.append(
                        f"技能不匹配，需要 {required_skill}"
                    )
                candidate_details.append(
                    {
                        "agent_id": candidate.agent_id,
                        "eligible": not excluded_reasons,
                        "excluded_reasons": excluded_reasons,
                        "load": candidate_load,
                        "max_conversations": candidate.max_conversations,
                        "risk_clearance": candidate.risk_clearance,
                        "skills": candidate.skills,
                        "load_ratio": round(
                            candidate_load
                            / max(candidate.max_conversations, 1),
                            4,
                        ),
                        "selected": False,
                    }
                )
            available = [
                agent
                for agent in online
                if loads.get(agent.agent_id, 0) < agent.max_conversations
                and _risk_rank(agent.risk_clearance) >= _risk_rank(risk_level)
                and (
                    not agent.skills
                    or required_skill is None
                    or required_skill in agent.skills
                )
            ]
            if not available:
                continue
            agent = min(
                available,
                key=lambda candidate: (
                    0
                    if risk_level in {"R2", "R3"}
                    and candidate.actor_role in {"supervisor", "admin"}
                    else 1,
                    (
                        loads.get(candidate.agent_id, 0)
                        / max(candidate.max_conversations, 1)
                    ),
                    _as_utc(candidate.last_seen_at),
                ),
            )
            conversation.assigned_agent_id = agent.agent_id
            conversation.assigned_at = datetime.now(UTC)
            conversation.version += 1
            loads[agent.agent_id] = loads.get(agent.agent_id, 0) + 1
            for candidate_detail in candidate_details:
                candidate_detail["selected"] = (
                    candidate_detail["agent_id"] == agent.agent_id
                )
            candidate_details.sort(
                key=lambda candidate_detail: (
                    bool(candidate_detail["selected"]),
                    bool(candidate_detail["eligible"]),
                    -float(candidate_detail["load_ratio"]),
                ),
                reverse=True,
            )
            reason_parts = [
                (
                    f"技能匹配“{required_skill}”"
                    if required_skill
                    else "当前工单未限定专用技能"
                ),
                (
                    f"风险权限 {agent.risk_clearance} "
                    f"覆盖 {risk_level}"
                ),
                (
                    f"当前负载 {loads[agent.agent_id] - 1}/"
                    f"{agent.max_conversations}"
                ),
            ]
            if (
                risk_level in {"R2", "R3"}
                and agent.actor_role in {"supervisor", "admin"}
            ):
                reason_parts.append("高风险会话优先交给主管")
            assignments.append(
                AssignmentResultItem(
                    conversation_id=conversation.id,
                    agent_id=agent.agent_id,
                    priority=item.priority,
                    reason="；".join(reason_parts) + "。",
                    candidates=candidate_details,
                )
            )
        self.session.commit()
        return AssignmentRunResult(
            assignments=assignments,
            assigned_count=len(assignments),
            unassigned_count=self.assignment_queue(business_unit_id).total,
        )

    def alerts(self, *, business_unit_id: str | None = None) -> CustomerServiceAlertList:
        now = datetime.now(UTC)
        statement = (
            select(CustomerConversation, Ticket)
            .outerjoin(Ticket, Ticket.id == CustomerConversation.current_ticket_id)
            .where(CustomerConversation.status == "ACTIVE")
        )
        if business_unit_id:
            statement = statement.where(
                CustomerConversation.business_unit_id == business_unit_id
            )
        rows = self.session.execute(statement).all()
        items: list[CustomerServiceAlertItem] = []
        for conversation, ticket in rows:
            last_message = self.session.scalar(
                select(CustomerMessage)
                .where(CustomerMessage.conversation_id == conversation.id)
                .order_by(CustomerMessage.sequence.desc())
                .limit(1)
            )
            if last_message is not None and last_message.role != "BUYER":
                continue
            priority = ticket.priority if ticket and ticket.priority else "P3"
            sla_seconds = self.SLA_SECONDS.get(priority, 600)
            waiting_from = (
                last_message.created_at
                if last_message is not None
                else conversation.created_at
            )
            waiting_seconds = max(
                0,
                round((now - _as_utc(waiting_from)).total_seconds()),
            )
            if waiting_seconds < sla_seconds:
                continue
            items.append(
                CustomerServiceAlertItem(
                    conversation_id=conversation.id,
                    requester_ref=conversation.requester_ref,
                    assigned_agent_id=conversation.assigned_agent_id,
                    priority=priority,
                    waiting_seconds=waiting_seconds,
                    sla_seconds=sla_seconds,
                    overdue_seconds=waiting_seconds - sla_seconds,
                )
            )
        items.sort(
            key=lambda item: (-item.overdue_seconds, item.conversation_id)
        )
        return CustomerServiceAlertList(items=items, total=len(items))

    def escalate_overdue_conversations(
        self,
        *,
        business_unit_id: str | None = None,
    ) -> int:
        escalated = 0
        for alert in self.alerts(
            business_unit_id=business_unit_id
        ).items:
            if alert.overdue_seconds < 300 or alert.priority in {"P0", "P1"}:
                continue
            target = "P1" if alert.overdue_seconds >= 900 else "P2"
            conversation = self.session.get(
                CustomerConversation, alert.conversation_id
            )
            if conversation is None:
                continue
            ticket = self.session.scalar(
                select(Ticket).where(
                    Ticket.id == conversation.current_ticket_id
                )
            )
            if ticket is None or ticket.priority == target:
                continue
            previous = ticket.priority
            ticket.priority = target
            record_audit(
                self.session,
                correlation_id=f"sla-escalation:{alert.conversation_id}",
                event_type="customer_service.sla.escalated",
                actor_type="SERVICE",
                actor_id="system.customer_service_sla",
                resource_type="customer_conversation",
                resource_id=alert.conversation_id,
                action="escalate_priority",
                decision="EXECUTED",
                payload={
                    "previous_priority": previous,
                    "new_priority": target,
                    "overdue_seconds": alert.overdue_seconds,
                },
            )
            escalated += 1
        self.session.commit()
        return escalated

    def sync_supervisor_notifications(
        self,
        business_unit_id: str | None = None,
    ) -> int:
        created = 0
        for alert in self.alerts(business_unit_id=business_unit_id).items:
            if alert.priority not in {"P0", "P1"}:
                continue
            existing = self.session.scalar(
                select(CustomerServiceNotification).where(
                    CustomerServiceNotification.conversation_id
                    == alert.conversation_id,
                    CustomerServiceNotification.status == "OPEN",
                )
            )
            if existing is not None:
                continue
            conversation = self.session.get(
                CustomerConversation, alert.conversation_id
            )
            if conversation is None:
                continue
            self.session.add(
                CustomerServiceNotification(
                    business_unit_id=conversation.business_unit_id,
                    conversation_id=conversation.id,
                    severity=alert.priority,
                    title=f"{alert.priority} 客服会话超时",
                    message=(
                        f"买家 {alert.requester_ref} 已等待 "
                        f"{alert.waiting_seconds} 秒，超过 SLA "
                        f"{alert.overdue_seconds} 秒。"
                    ),
                )
            )
            created += 1
        self.session.commit()
        return created

    def notifications(self, *, business_unit_id: str) -> CustomerServiceNotificationList:
        items = list(
            self.session.scalars(
                select(CustomerServiceNotification)
                .where(
                    CustomerServiceNotification.business_unit_id == business_unit_id
                )
                .order_by(CustomerServiceNotification.created_at.desc())
                .limit(100)
            ).all()
        )
        return CustomerServiceNotificationList(
            items=[self.notification_view(item) for item in items],
            total=len(items),
        )

    def metrics(self, *, business_unit_id: str) -> CustomerServiceMetrics:
        conversations = list(
            self.session.scalars(
                select(CustomerConversation).where(
                    CustomerConversation.business_unit_id == business_unit_id,
                    CustomerConversation.status != "ARCHIVED",
                )
            ).all()
        )
        active = [item for item in conversations if item.status == "ACTIVE"]
        alerts = self.alerts(business_unit_id=business_unit_id)
        notifications = self.notifications(business_unit_id=business_unit_id)
        now = datetime.now(UTC)
        waiting = [
            max(0, round((now - _as_utc(item.created_at)).total_seconds()))
            for item in active
        ]
        total_messages = self.session.scalar(
            select(func.count())
            .select_from(CustomerMessage)
            .join(
                CustomerConversation,
                CustomerConversation.id == CustomerMessage.conversation_id,
            )
            .where(
                CustomerConversation.business_unit_id == business_unit_id,
                CustomerConversation.status != "ARCHIVED",
            )
        ) or 0
        ticket_ids = [
            item.current_ticket_id
            for item in active
            if item.current_ticket_id is not None
        ]
        ticket_rows = (
            self.session.execute(
                select(Ticket.id, Ticket.risk_level).where(
                    Ticket.id.in_(ticket_ids)
                )
            ).all()
            if ticket_ids
            else []
        )
        risk_by_ticket = {
            ticket_id: risk_level
            for ticket_id, risk_level in ticket_rows
        }
        risk_counts = {"R0": 0, "R1": 0, "R2": 0, "R3": 0, "UNKNOWN": 0}
        for item in active:
            risk_level = (
                risk_by_ticket.get(item.current_ticket_id)
                if item.current_ticket_id is not None
                else None
            )
            risk_counts[
                risk_level if risk_level in risk_counts else "UNKNOWN"
            ] += 1
        assignment_queue = self.assignment_queue(business_unit_id)
        return CustomerServiceMetrics(
            total_conversations=len(conversations),
            active_conversations=len(active),
            unassigned_conversations=assignment_queue.total,
            online_agents=self.presence(business_unit_id).online_count,
            sla_overdue=alerts.total,
            open_supervisor_notifications=sum(
                item.status == "OPEN" for item in notifications.items
            ),
            average_waiting_seconds=(
                round(sum(waiting) / len(waiting)) if waiting else 0
            ),
            total_messages=int(total_messages),
            risk_counts=risk_counts,
        )

    def history_metrics(
        self,
        *,
        business_unit_id: str,
        days: int,
    ) -> CustomerServiceHistoryMetrics:
        now = datetime.now(UTC)
        end_day = now.date()
        start_day = end_day - timedelta(days=days - 1)
        start = datetime.combine(start_day, time.min, tzinfo=UTC)
        conversations = list(
            self.session.scalars(
                select(CustomerConversation).where(
                    CustomerConversation.business_unit_id == business_unit_id,
                    CustomerConversation.created_at >= start,
                    CustomerConversation.status != "ARCHIVED",
                )
            ).all()
        )
        messages = list(
            self.session.scalars(
                select(CustomerMessage)
                .join(
                    CustomerConversation,
                    CustomerConversation.id == CustomerMessage.conversation_id,
                )
                .where(
                    CustomerConversation.business_unit_id == business_unit_id,
                    CustomerMessage.created_at >= start,
                    CustomerConversation.status != "ARCHIVED",
                )
            ).all()
        )
        by_conversation: dict[UUID, list[CustomerMessage]] = {}
        for message in messages:
            by_conversation.setdefault(message.conversation_id, []).append(message)
        response_times: list[int] = []
        daily: dict[str, dict[str, object]] = {}
        for index in range(days):
            key = (start_day + timedelta(days=index)).isoformat()
            daily[key] = {
                "conversations_created": 0,
                "messages": 0,
                "buyer_messages": 0,
                "assistant_messages": 0,
                "first_responses": [],
            }
        for conversation in conversations:
            key = _as_utc(conversation.created_at).date().isoformat()
            if key in daily:
                daily[key]["conversations_created"] = _integer_value(
                    daily[key]["conversations_created"]
                ) + 1
            ordered = sorted(
                by_conversation.get(conversation.id, []),
                key=lambda item: item.sequence,
            )
            buyer = next((item for item in ordered if item.role == "BUYER"), None)
            assistant = next(
                (
                    item
                    for item in ordered
                    if item.role == "ASSISTANT"
                    and buyer is not None
                    and item.sequence > buyer.sequence
                ),
                None,
            )
            if buyer and assistant and key in daily:
                seconds = max(
                    0,
                    round(
                        (
                            _as_utc(assistant.created_at)
                            - _as_utc(buyer.created_at)
                        ).total_seconds()
                    ),
                )
                response_times.append(seconds)
                cast_list = daily[key]["first_responses"]
                if isinstance(cast_list, list):
                    cast_list.append(seconds)
        for message in messages:
            key = _as_utc(message.created_at).date().isoformat()
            if key not in daily:
                continue
            daily[key]["messages"] = _integer_value(daily[key]["messages"]) + 1
            if message.role == "BUYER":
                daily[key]["buyer_messages"] = (
                    _integer_value(daily[key]["buyer_messages"]) + 1
                )
            elif message.role == "ASSISTANT":
                daily[key]["assistant_messages"] = (
                    _integer_value(daily[key]["assistant_messages"]) + 1
                )
        daily_items = []
        for key, values in daily.items():
            responses = values["first_responses"]
            daily_items.append(
                CustomerDailyMetric(
                    date=key,
                    conversations_created=_integer_value(
                        values["conversations_created"]
                    ),
                    messages=_integer_value(values["messages"]),
                    buyer_messages=_integer_value(values["buyer_messages"]),
                    assistant_messages=_integer_value(
                        values["assistant_messages"]
                    ),
                    average_first_response_seconds=(
                        round(sum(responses) / len(responses))
                        if isinstance(responses, list) and responses
                        else None
                    ),
                )
            )
        active = [item for item in conversations if item.status == "ACTIVE"]
        unassigned = sum(item.assigned_agent_id is None for item in active)
        return CustomerServiceHistoryMetrics(
            days=days,
            conversations_created=len(conversations),
            messages=len(messages),
            unassigned_rate=round(unassigned / len(active), 4) if active else 0.0,
            average_first_response_seconds=(
                round(sum(response_times) / len(response_times))
                if response_times
                else None
            ),
            daily=daily_items,
        )

    def get_notification(
        self,
        notification_id: UUID,
    ) -> CustomerServiceNotification:
        notification = self.session.get(CustomerServiceNotification, notification_id)
        if notification is None:
            raise ApiProblem(
                status_code=404,
                code="NOTIFICATION_NOT_FOUND",
                title="Notification not found",
                detail=f"Notification {notification_id} does not exist.",
            )
        return notification

    def acknowledge_notification(
        self,
        notification_id: UUID,
        *,
        actor_id: str,
    ) -> CustomerServiceNotification:
        notification = self.get_notification(notification_id)
        notification.status = "ACKNOWLEDGED"
        notification.acknowledged_by = actor_id
        notification.acknowledged_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(notification)
        return notification

    def reassign(
        self,
        conversation_id: UUID,
        payload: ConversationReassignRequest,
        *,
        supervisor_id: str,
        correlation_id: str,
    ) -> CustomerConversation:
        conversation = self.session.scalar(
            select(CustomerConversation)
            .where(CustomerConversation.id == conversation_id)
            .with_for_update()
        )
        if conversation is None:
            return self.get(conversation_id)
        if conversation.version != payload.expected_version:
            raise ApiProblem(
                status_code=409,
                code="CONVERSATION_VERSION_CONFLICT",
                title="Conversation was updated",
                detail="Refresh the conversation before reassignment.",
            )
        previous_agent = conversation.assigned_agent_id
        conversation.assigned_agent_id = payload.agent_id
        conversation.assigned_at = datetime.now(UTC)
        conversation.version += 1
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="customer_service.conversation.reassigned",
            actor_type="USER",
            actor_id=supervisor_id,
            resource_type="customer_conversation",
            resource_id=conversation.id,
            action="reassign",
            decision="EXECUTED",
            reason_code=payload.reason,
            payload={
                "previous_agent_id": previous_agent,
                "new_agent_id": payload.agent_id,
            },
        )
        self.session.commit()
        self.session.refresh(conversation)
        return conversation

    def notification_view(
        self, notification: CustomerServiceNotification
    ) -> CustomerServiceNotificationView:
        return CustomerServiceNotificationView(
            id=notification.id,
            business_unit_id=notification.business_unit_id,
            conversation_id=notification.conversation_id,
            severity=notification.severity,
            title=notification.title,
            message=notification.message,
            status=notification.status,
            acknowledged_by=notification.acknowledged_by,
            acknowledged_at=notification.acknowledged_at,
            created_at=notification.created_at,
        )

    def get(self, conversation_id: UUID) -> CustomerConversation:
        conversation = self.session.get(CustomerConversation, conversation_id)
        if conversation is None:
            raise ApiProblem(
                status_code=404,
                code="CONVERSATION_NOT_FOUND",
                title="Conversation not found",
                detail=f"Conversation {conversation_id} does not exist.",
            )
        return conversation

    def get_turn(
        self, conversation_id: UUID, turn_id: UUID
    ) -> ConversationTurn:
        turn = self.session.scalar(
            select(ConversationTurn).where(
                ConversationTurn.id == turn_id,
                ConversationTurn.conversation_id == conversation_id,
            )
        )
        if turn is None:
            raise ApiProblem(
                status_code=404,
                code="CONVERSATION_TURN_NOT_FOUND",
                title="Conversation turn not found",
                detail=(
                    f"Conversation turn {turn_id} does not exist in "
                    f"conversation {conversation_id}."
                ),
            )
        return turn

    def turn_events(
        self,
        turn_id: UUID,
        *,
        after_sequence: int | None = None,
        limit: int | None = None,
    ) -> list[ConversationTurnEvent]:
        return list_turn_events(
            self.session,
            turn_id=turn_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def turn_event_count(self, turn_id: UUID) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(ConversationTurnEvent)
                .where(ConversationTurnEvent.turn_id == turn_id)
            )
            or 0
        )

    def turn_by_id(self, turn_id: UUID) -> ConversationTurn:
        turn = self.session.get(ConversationTurn, turn_id)
        if turn is None:
            raise ApiProblem(
                status_code=404,
                code="CONVERSATION_TURN_NOT_FOUND",
                title="Conversation turn not found",
                detail=f"Conversation turn {turn_id} does not exist.",
            )
        return turn

    def turns(
        self,
        conversation_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> ConversationTurnList:
        condition = ConversationTurn.conversation_id == conversation_id
        total = (
            self.session.scalar(
                select(func.count())
                .select_from(ConversationTurn)
                .where(condition)
            )
            or 0
        )
        rows = self.session.scalars(
            select(ConversationTurn)
            .where(condition)
            .order_by(ConversationTurn.sequence.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return ConversationTurnList(
            items=[self.turn_view(row) for row in rows],
            total=total,
        )

    def turn_detail(self, turn: ConversationTurn) -> ConversationTurnDetailView:
        return ConversationTurnDetailView(
            **self.turn_view(turn).model_dump(),
            context=turn.context_json,
            skill_code=turn.skill_code,
            skill_version=turn.skill_version,
            skill_snapshot=turn.skill_snapshot_json,
            completion=turn.completion_json,
        )

    def handoffs(
        self,
        conversation_id: UUID,
        *,
        limit: int = 100,
    ) -> ConversationHandoffList:
        rows = self.session.scalars(
            select(ConversationHandoff)
            .where(ConversationHandoff.conversation_id == conversation_id)
            .order_by(ConversationHandoff.created_at.asc())
            .limit(limit)
        ).all()
        return ConversationHandoffList(
            items=[self.handoff_view(row) for row in rows],
            total=len(rows),
        )

    def retry_turn(
        self,
        turn_id: UUID,
        *,
        actor_id: str,
        correlation_id: str,
    ) -> ConversationTurn:
        """Put a retryable turn back in the queue.

        Only ``FAILED_RETRYABLE`` can be retried: a finished turn must not be
        replayed (it already wrote messages and ticket state), and a queued or
        running turn is already owned by a worker.
        """
        turn = self.session.scalar(
            select(ConversationTurn)
            .where(ConversationTurn.id == turn_id)
            .with_for_update()
        )
        if turn is None:
            raise ApiProblem(
                status_code=404,
                code="CONVERSATION_TURN_NOT_FOUND",
                title="Conversation turn not found",
                detail=f"Conversation turn {turn_id} does not exist.",
            )
        status = parse_turn_status(turn.status)
        if status in TERMINAL_TURN_STATUSES:
            raise ApiProblem(
                status_code=409,
                code="TURN_ALREADY_TERMINAL",
                title="Turn is already terminal",
                detail=f"Turn {turn_id} is {status.value} and cannot be retried.",
            )
        if status in {TurnStatus.PENDING, TurnStatus.RUNNING}:
            raise ApiProblem(
                status_code=409,
                code="TURN_IN_PROGRESS",
                title="Turn is already in progress",
                detail=f"Turn {turn_id} is {status.value}.",
            )
        transition_turn(
            self.session,
            turn,
            TurnStatus.PENDING,
            reason_code="OPERATOR_RETRY",
            actor_id=actor_id,
            actor_type="AGENT",
            correlation_id=correlation_id,
            stage_label="等待重试",
            payload={"previous_status": status.value},
        )
        turn.lease_expires_at = new_lease(
            get_settings().conversation_turn_lease_seconds
        )
        turn.error_code = None
        turn.error_message = None
        turn.completed_at = None
        self.session.commit()
        self.session.refresh(turn)
        return turn

    def operational_turns(
        self,
        *,
        business_unit_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> OperationalTurnList:
        condition = CustomerConversation.business_unit_id == business_unit_id
        if status:
            condition = condition & (ConversationTurn.status == status)
        total = (
            self.session.scalar(
                select(func.count())
                .select_from(ConversationTurn)
                .join(
                    CustomerConversation,
                    CustomerConversation.id == ConversationTurn.conversation_id,
                )
                .where(condition)
            )
            or 0
        )
        rows = self.session.execute(
            select(ConversationTurn, CustomerConversation)
            .join(
                CustomerConversation,
                CustomerConversation.id == ConversationTurn.conversation_id,
            )
            .where(condition)
            .order_by(ConversationTurn.created_at.desc())
            .limit(limit)
        ).all()
        return OperationalTurnList(
            items=[
                OperationalTurnView(
                    id=turn.id,
                    conversation_id=turn.conversation_id,
                    ticket_id=turn.ticket_id,
                    business_unit_id=conversation.business_unit_id,
                    requester_ref=conversation.requester_ref,
                    sequence=turn.sequence,
                    status=turn.status,
                    stage_label=turn.stage_label,
                    correlation_id=turn.correlation_id,
                    attempt_count=turn.attempt_count,
                    gate_decision=(
                        str(turn.gate_json.get("decision"))
                        if turn.gate_json
                        and turn.gate_json.get("decision") is not None
                        else None
                    ),
                    error_code=turn.error_code,
                    error_message=turn.error_message,
                    lease_expires_at=turn.lease_expires_at,
                    created_at=turn.created_at,
                    updated_at=turn.updated_at,
                )
                for turn, conversation in rows
            ],
            total=total,
        )

    def runtime_health(
        self,
        *,
        business_unit_id: str,
        window_hours: int = 24,
    ) -> RuntimeHealthView:
        """Runtime counters an operator needs before trusting auto-send.

        Rates are computed over the window's turns; a NULL gate (pre-M3 turn)
        counts as neither auto-send nor review. Scanning rows in Python keeps
        the calculation identical on PostgreSQL and SQLite; the window keeps
        it bounded.
        """
        now = datetime.now(UTC)
        since = now - timedelta(hours=window_hours)
        turns = list(
            self.session.scalars(
                select(ConversationTurn)
                .join(
                    CustomerConversation,
                    CustomerConversation.id == ConversationTurn.conversation_id,
                )
                .where(
                    CustomerConversation.business_unit_id == business_unit_id,
                    ConversationTurn.created_at >= since,
                )
            ).all()
        )
        decisions = [
            str(turn.gate_json.get("decision"))
            for turn in turns
            if turn.gate_json and turn.gate_json.get("decision")
        ]
        auto_send_count = sum(1 for item in decisions if item == "AUTO_SEND")
        human_review_count = sum(
            1 for item in decisions if item == "HUMAN_REVIEW"
        )
        blocked_count = sum(1 for item in decisions if item == "BLOCK")
        unverified_count = sum(
            1
            for turn in turns
            if turn.grounding_status in {"UNVERIFIED", "UNSUPPORTED"}
        )
        handoff_count = (
            self.session.scalar(
                select(func.count())
                .select_from(ConversationHandoff)
                .join(
                    CustomerConversation,
                    CustomerConversation.id
                    == ConversationHandoff.conversation_id,
                )
                .where(
                    CustomerConversation.business_unit_id == business_unit_id,
                    ConversationHandoff.created_at >= since,
                )
            )
            or 0
        )
        stuck_turn_count = (
            self.session.scalar(
                select(func.count())
                .select_from(ConversationTurn)
                .join(
                    CustomerConversation,
                    CustomerConversation.id == ConversationTurn.conversation_id,
                )
                .where(
                    CustomerConversation.business_unit_id == business_unit_id,
                    ConversationTurn.status.in_(
                        [TurnStatus.PENDING.value, TurnStatus.RUNNING.value]
                    ),
                    ConversationTurn.lease_expires_at.is_not(None),
                    ConversationTurn.lease_expires_at < now,
                )
            )
            or 0
        )
        # ``max(uuid)`` does not exist on PostgreSQL, so aggregate the task id
        # as text; any linked repair task is enough to tell the operator the
        # gap already has one.
        top_gaps = [
            RuntimeGapItem(
                query=query,
                occurrence_count=int(count),
                repair_task_id=(
                    UUID(str(raw_task_id)) if raw_task_id else None
                ),
            )
            for query, count, raw_task_id in self.session.execute(
                select(
                    KnowledgeGapOccurrence.normalized_query,
                    func.count(KnowledgeGapOccurrence.id),
                    func.max(
                        cast(KnowledgeGapOccurrence.repair_task_id, String)
                    ),
                )
                .where(
                    KnowledgeGapOccurrence.business_unit_id == business_unit_id,
                    KnowledgeGapOccurrence.created_at >= since,
                )
                .group_by(KnowledgeGapOccurrence.normalized_query)
                .order_by(func.count(KnowledgeGapOccurrence.id).desc())
                .limit(5)
            ).all()
        ]
        turn_count = len(turns)
        return RuntimeHealthView(
            business_unit_id=business_unit_id,
            window_hours=window_hours,
            turn_count=turn_count,
            completed_count=sum(
                1 for turn in turns if turn.status == TurnStatus.COMPLETED.value
            ),
            needs_human_count=sum(
                1 for turn in turns if turn.status == TurnStatus.NEEDS_HUMAN.value
            ),
            failed_count=sum(
                1
                for turn in turns
                if turn.status
                in {
                    TurnStatus.FAILED_RETRYABLE.value,
                    TurnStatus.FAILED_TERMINAL.value,
                }
            ),
            cancelled_count=sum(
                1 for turn in turns if turn.status == TurnStatus.CANCELLED.value
            ),
            auto_send_count=auto_send_count,
            human_review_count=human_review_count,
            blocked_count=blocked_count,
            unverified_count=unverified_count,
            handoff_count=int(handoff_count),
            stuck_turn_count=int(stuck_turn_count),
            auto_send_rate=(
                auto_send_count / turn_count if turn_count else None
            ),
            unverified_rate=(
                unverified_count / turn_count if turn_count else None
            ),
            handoff_rate=(
                int(handoff_count) / turn_count if turn_count else None
            ),
            top_gaps=top_gaps,
        )

    def append_buyer_message(
        self,
        conversation_id: UUID,
        payload: CustomerMessageCreate,
        *,
        principal: Principal,
        correlation_id: str,
    ) -> BuyerMessageResult:
        """Accept one buyer message; a lost deadlock retries in a fresh transaction.

        A retry is safe because nothing was committed: the idempotency key is
        re-checked inside the new transaction and still suppresses a replay.
        """
        return run_with_deadlock_retry(
            self.session,
            f"buyer message on {conversation_id}",
            lambda: self._append_buyer_message_once(
                conversation_id,
                payload,
                principal=principal,
                correlation_id=correlation_id,
            ),
        )

    def _append_buyer_message_once(
        self,
        conversation_id: UUID,
        payload: CustomerMessageCreate,
        *,
        principal: Principal,
        correlation_id: str,
    ) -> BuyerMessageResult:
        conversation = self.session.scalar(
            select(CustomerConversation)
            .where(CustomerConversation.id == conversation_id)
            .with_for_update()
        )
        if conversation is None:
            raise ApiProblem(
                status_code=404,
                code="CONVERSATION_NOT_FOUND",
                title="Conversation not found",
                detail=f"Conversation {conversation_id} does not exist.",
            )
        if payload.client_message_id:
            replay = self.session.scalar(
                select(ConversationTurn).where(
                    ConversationTurn.conversation_id == conversation.id,
                    ConversationTurn.client_message_id
                    == payload.client_message_id,
                )
            )
            if replay is not None:
                # Same message submitted twice: return what the first submit
                # produced instead of writing a second message and turn.
                return BuyerMessageResult(
                    conversation=conversation,
                    turn_id=None,
                    replayed=True,
                )
        enterprise_service = conversation.channel.startswith("enterprise")
        source_system = (
            "enterprise_service_desk" if enterprise_service else "ecommerce_demo"
        )
        # The ticket body is the current question only. Earlier messages stay
        # in the conversation and are assembled as structured context by the
        # runtime; copying them into the ticket duplicated text and made the
        # ticket drift from the message it belongs to.
        body = payload.content.strip()
        sequence = self._next_sequence(conversation.id)
        # A human owns the conversation: no digital answer may talk over them.
        # The message is still stored so the human can see and answer it.
        human_owner_id = conversation.assigned_agent_id
        small_talk_kind = classify_small_talk(payload.content)
        small_talk_employee = (
            self.session.get(DigitalEmployee, conversation.employee_id)
            if conversation.employee_id
            else None
        )
        small_talk_reply = (
            None
            if human_owner_id is not None
            else _small_talk_reply(
                payload.content,
                enterprise_service=enterprise_service,
                kind=small_talk_kind,
                employee=small_talk_employee,
            )
        )
        if small_talk_reply is not None:
            # Greetings and self-introduction need no evidence, so the gate
            # clears them explicitly. Leaving gate_json NULL would make the
            # connector treat them as unreviewed and never auto-send.
            small_talk_gate = evaluate_gate(
                GateContext(
                    grounding_status="NOT_REQUIRED",
                    claims=[],
                    citations=[],
                    risk_level=None,
                    ticket_needs_human=False,
                    skill_completion=None,
                    path="small_talk",
                )
            )
            ticket_id = conversation.current_ticket_id
            buyer_message = CustomerMessage(
                conversation_id=conversation.id,
                sequence=sequence,
                role="BUYER",
                content=payload.content.strip(),
                ticket_id=ticket_id,
                created_by=principal.actor_id,
            )
            self.session.add(buyer_message)
            self.session.flush()
            # The fast path reads what the conversation already established:
            # memory facts and the latest handoff. Without this the greeting
            # ignored everything the buyer had said before it.
            fast_path_context = assemble_context(
                self.session,
                conversation_id=conversation.id,
                current_message=buyer_message,
            )
            small_talk_reply = (
                _small_talk_reply(
                    payload.content,
                    enterprise_service=enterprise_service,
                    kind=small_talk_kind,
                    employee=small_talk_employee,
                    memory=fast_path_context.memory,
                )
                or small_talk_reply
            )
            assistant_message = CustomerMessage(
                conversation_id=conversation.id,
                sequence=sequence + 1,
                role="ASSISTANT",
                content=small_talk_reply,
                ticket_id=ticket_id,
                created_by="digital_employee",
            )
            self.session.add(assistant_message)
            self.session.flush()
            lease_seconds = get_settings().conversation_turn_lease_seconds
            turn = ConversationTurn(
                conversation_id=conversation.id,
                ticket_id=ticket_id,
                sequence=self._next_turn_sequence(conversation.id),
                status=TurnStatus.PENDING.value,
                stage_label="问候已直接回复",
                user_message_id=buyer_message.id,
                assistant_message_id=assistant_message.id,
                employee_id=conversation.employee_id,
                intent="small_talk",
                correlation_id=correlation_id,
                client_message_id=payload.client_message_id,
                attempt_count=1,
                lease_expires_at=new_lease(lease_seconds),
                analysis_json={
                    "small_talk_kind": small_talk_kind,
                },
                context_json=fast_path_context.payload,
                response_provider="deterministic",
                response_model=(
                    "employee-self-introduction-v1"
                    if small_talk_kind == "identity"
                    else "small-talk-v1"
                ),
                grounding_status="NOT_REQUIRED",
                gate_json=jsonable_encoder(small_talk_gate),
                citations_json=[],
                trace_json=["small_talk_fast_path"],
                tool_calls_json=[],
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
            self.session.add(turn)
            self.session.flush()
            buyer_message.turn_id = turn.id
            assistant_message.turn_id = turn.id
            record_turn_event(
                self.session,
                turn,
                event_type="TURN_CREATED",
                actor_id="digital_employee.small_talk",
                correlation_id=correlation_id,
                payload={"fast_path": "small_talk"},
            )
            record_turn_event(
                self.session,
                turn,
                event_type="CONTEXT_ASSEMBLED",
                actor_id="digital_employee.small_talk",
                correlation_id=correlation_id,
                payload={**fast_path_context.payload, "fast_path": "small_talk"},
            )
            transition_turn(
                self.session,
                turn,
                TurnStatus.RUNNING,
                reason_code="SMALL_TALK_FAST_PATH",
                actor_id="digital_employee.small_talk",
                correlation_id=correlation_id,
            )
            record_turn_event(
                self.session,
                turn,
                event_type="GATE_EVALUATED",
                actor_id="digital_employee.small_talk",
                correlation_id=correlation_id,
                payload={
                    "decision": small_talk_gate["decision"],
                    "reasons": small_talk_gate["reasons"],
                    "version": small_talk_gate["version"],
                },
            )
            transition_turn(
                self.session,
                turn,
                TurnStatus.COMPLETED,
                reason_code="SMALL_TALK_ANSWERED",
                actor_id="digital_employee.small_talk",
                correlation_id=correlation_id,
                stage_label="问候已直接回复",
                payload={
                    "grounding_status": "NOT_REQUIRED",
                    "small_talk_kind": small_talk_kind,
                    "gate_decision": small_talk_gate["decision"],
                },
            )
            turn.lease_expires_at = None
            self._update_memory(
                conversation.id,
                turn.sequence,
                payload.content,
                small_talk_reply,
                turn_id=turn.id,
            )
            conversation.status = "ACTIVE"
            conversation.version += 1
            record_audit(
                self.session,
                correlation_id=correlation_id,
                event_type="customer_service.small_talk.answered",
                actor_type="SERVICE",
                actor_id="digital_employee.small_talk",
                resource_type="customer_conversation",
                resource_id=conversation.id,
                action="answer",
                decision="EXECUTED",
                payload={"message": payload.content.strip()},
            )
            self.session.commit()
            self.session.refresh(conversation)
            return BuyerMessageResult(
                conversation=conversation,
                turn_id=None,
                replayed=False,
            )
        existing_ticket = (
            self.session.get(Ticket, conversation.current_ticket_id)
            if conversation.current_ticket_id
            else None
        )
        if existing_ticket is None:
            # TicketService.create commits before the caller records
            # current_ticket_id, so two first messages that arrive at the same
            # instant can both reach the creation branch. The loser finds the
            # ticket the winner already committed and joins it instead of
            # failing on the idempotency key.
            existing_ticket = self._conversation_initial_ticket(
                conversation, source_system
            )
        if existing_ticket is not None:
            ticket = existing_ticket
            created = True
            previous_employee_id = ticket.employee_id
            reroute_reason = self._maybe_reroute_employee(
                conversation=conversation,
                ticket=ticket,
                content=payload.content,
                turn_sequence=self._next_turn_sequence(conversation.id),
                correlation_id=correlation_id,
            )
            ticket.subject = payload.content.strip().splitlines()[0][:120]
            ticket.body = body
            if human_owner_id is not None:
                # A human is answering this conversation. Reopening the ticket
                # as RECEIVED would make the workbench refuse their reply, and
                # resetting it would look like the employee is still handling
                # it.
                ticket.status = TicketStatus.WAITING_HUMAN
                ticket.needs_human = True
                ticket.human_reason = "HUMAN_TAKEOVER"
                if ticket.workflow_state == WorkflowState.RECEIVED:
                    transition_ticket(
                        self.session,
                        ticket,
                        WorkflowState.NEEDS_HUMAN,
                        reason_code="HUMAN_TAKEOVER",
                        actor_type="USER",
                        actor_id=human_owner_id,
                    )
                elif ticket.workflow_state == WorkflowState.COMPLETED:
                    # A finished ticket is not reopened by the takeover itself;
                    # it only reopens once the buyer speaks again while a human
                    # owns the conversation. Without this edge the workbench
                    # rejects the human reply as "already completed".
                    transition_ticket(
                        self.session,
                        ticket,
                        WorkflowState.RECEIVED,
                        reason_code="CONVERSATION_REOPENED",
                        actor_type="USER",
                        actor_id=human_owner_id,
                        allow_terminal=True,
                    )
                    transition_ticket(
                        self.session,
                        ticket,
                        WorkflowState.NEEDS_HUMAN,
                        reason_code="HUMAN_TAKEOVER",
                        actor_type="USER",
                        actor_id=human_owner_id,
                    )
            else:
                ticket.status = TicketStatus.OPEN
                ticket.workflow_state = WorkflowState.RECEIVED
            ticket.version += 1
        else:
            previous_employee_id = None
            reroute_reason = None
            ticket, created, _event_id = TicketService(self.session).create(
                payload=TicketCreate(
                    business_unit_id=conversation.business_unit_id,
                    employee_id=conversation.employee_id,
                    source=SourceInput(
                        system=source_system,
                        channel=conversation.channel,
                        external_ticket_id=(
                            f"CONV-{conversation.id}-initial"
                        ),
                    ),
                    requester=RequesterInput(
                        external_ref=conversation.requester_ref,
                        customer_tier="standard",
                    ),
                    subject=payload.content.strip().splitlines()[0][:120],
                    body=body,
                    locale="zh-CN",
                    attachments=[],
                    metadata={
                        "channel": source_system,
                        **(
                            {
                                "service_entry_id": str(
                                    conversation.service_entry_id
                                )
                            }
                            if conversation.service_entry_id
                            else {}
                        ),
                        **(
                            {"service_domain": "enterprise"}
                            if enterprise_service
                            else {
                                "category": (
                                    conversation.category_name
                                    if conversation.category_name
                                    else "商品"
                                )
                            }
                        ),
                        **(
                            {"product_id": payload.product_id}
                            if payload.product_id
                            else {}
                        ),
                        **({"sku": payload.sku} if payload.sku else {}),
                    },
                ),
                idempotency_key=(
                    f"conversation:{conversation.id}:initial"
                ),
                principal=principal,
                correlation_id=correlation_id,
                enqueue=False,
                # Keep this conversation's row lock until this request commits:
                # a concurrent message must not pick the same message sequence.
                commit=False,
            )
        if created:
            # Snapshot the turn this message continues before the new one
            # exists; a handoff summarises the predecessor, not the successor.
            previous_turn = latest_turn(self.session, conversation.id)
            buyer_message = CustomerMessage(
                conversation_id=conversation.id,
                sequence=sequence,
                role="BUYER",
                content=payload.content.strip(),
                ticket_id=ticket.id,
                created_by=principal.actor_id,
            )
            self.session.add(buyer_message)
            self.session.flush()
            employee = (
                self.session.get(DigitalEmployee, ticket.employee_id)
                if ticket.employee_id
                else None
            )
            turn = ConversationTurn(
                conversation_id=conversation.id,
                ticket_id=ticket.id,
                sequence=self._next_turn_sequence(conversation.id),
                status=TurnStatus.PENDING.value,
                stage_label="正在识别问题",
                user_message_id=buyer_message.id,
                employee_id=ticket.employee_id,
                employee_config_revision=(
                    employee.config_revision if employee else None
                ),
                correlation_id=correlation_id,
                client_message_id=payload.client_message_id,
                lease_expires_at=new_lease(
                    get_settings().conversation_turn_lease_seconds
                ),
                analysis_json={},
                citations_json=[],
                trace_json=[],
                tool_calls_json=[],
                started_at=datetime.now(UTC),
            )
            self.session.add(turn)
            self.session.flush()
            buyer_message.turn_id = turn.id
            if (
                previous_employee_id is not None
                and ticket.employee_id is not None
                and ticket.employee_id != previous_employee_id
            ):
                # The router moved the conversation to another employee: this
                # turn must inherit what the previous one established.
                handoff = create_handoff(
                    self.session,
                    conversation=conversation,
                    from_turn=previous_turn,
                    to_employee=employee,
                    kind="AUTO_REROUTE",
                    reason_code=reroute_reason or "TOPIC_CHANGED",
                    actor_id="digital_employee.router",
                    correlation_id=correlation_id,
                    # The reroute already moved the conversation; the
                    # previous employee is the one the turn started with.
                    from_employee_id=previous_employee_id,
                )
                handoff.to_turn_id = turn.id
                turn.handoff_id = handoff.id
            record_turn_event(
                self.session,
                turn,
                event_type="TURN_CREATED",
                actor_id=principal.actor_id,
                actor_type="USER",
                correlation_id=correlation_id,
                payload={
                    "ticket_id": str(ticket.id),
                    "employee_id": (
                        str(ticket.employee_id) if ticket.employee_id else None
                    ),
                },
            )
            conversation.current_ticket_id = ticket.id
            if conversation.employee_id is None:
                conversation.employee_id = ticket.employee_id
            conversation.status = "ACTIVE"
            if human_owner_id is not None:
                # A human owns the conversation right now: this turn exists so
                # the message is visible and replayable, but it must never be
                # claimed by the digital worker. NEEDS_HUMAN is terminal, and
                # the router only dispatches PENDING turns.
                # The ticket the first message just created must say a human
                # owns it too; left in RECEIVED the workbench treats it as
                # waiting for the digital employee and refuses the reply.
                ticket.status = TicketStatus.WAITING_HUMAN
                ticket.needs_human = True
                ticket.human_reason = "HUMAN_TAKEOVER"
                if ticket.workflow_state == WorkflowState.RECEIVED:
                    transition_ticket(
                        self.session,
                        ticket,
                        WorkflowState.NEEDS_HUMAN,
                        reason_code="HUMAN_TAKEOVER",
                        actor_type="USER",
                        actor_id=human_owner_id,
                    )
                ticket.version += 1
                transition_turn(
                    self.session,
                    turn,
                    TurnStatus.RUNNING,
                    reason_code="HUMAN_HANDLING",
                    actor_id=human_owner_id,
                    actor_type="AGENT",
                    correlation_id=correlation_id,
                )
                transition_turn(
                    self.session,
                    turn,
                    TurnStatus.NEEDS_HUMAN,
                    reason_code="HUMAN_TAKEOVER",
                    actor_id=human_owner_id,
                    actor_type="AGENT",
                    correlation_id=correlation_id,
                    stage_label="已由人工接管，等待人工回复",
                    payload={"handover_agent_id": human_owner_id},
                )
                turn.lease_expires_at = None
                self.session.commit()
                self.session.refresh(conversation)
                return BuyerMessageResult(
                    conversation=conversation,
                    turn_id=None,
                    replayed=False,
                )
            from ticket_agent.digital_employees.models import (
                DigitalEmployeeRouteDecision,
            )

            route_decision = self.session.scalar(
                select(DigitalEmployeeRouteDecision).where(
                    DigitalEmployeeRouteDecision.ticket_id == ticket.id
                )
            )
            if route_decision is not None:
                route_decision.conversation_id = conversation.id
            self.session.commit()
            self.session.refresh(conversation)
            return BuyerMessageResult(
                conversation=conversation,
                turn_id=turn.id,
                replayed=False,
            )
        return BuyerMessageResult(
            conversation=conversation,
            turn_id=None,
            replayed=False,
        )

    def append_assistant_reply(self, ticket_id: UUID, content: str) -> None:
        buyer_message = self.session.scalar(
            select(CustomerMessage)
            .where(CustomerMessage.ticket_id == ticket_id, CustomerMessage.role == "BUYER")
            .order_by(CustomerMessage.sequence)
            .limit(1)
        )
        if buyer_message is None:
            return
        conversation = self.session.scalar(
            select(CustomerConversation)
            .where(CustomerConversation.id == buyer_message.conversation_id)
            .with_for_update()
        )
        if conversation is None:
            return
        self.session.add(
            CustomerMessage(
                conversation_id=conversation.id,
                sequence=self._next_sequence(conversation.id),
                role="ASSISTANT",
                content=content,
                ticket_id=ticket_id,
                created_by="digital_employee",
            )
        )
        self.session.commit()

    def messages(self, conversation_id: UUID) -> list[CustomerMessage]:
        return list(
            self.session.scalars(
                select(CustomerMessage)
                .where(CustomerMessage.conversation_id == conversation_id)
                .order_by(CustomerMessage.sequence)
            ).all()
        )

    def list(self, business_unit_id: str) -> CustomerConversationList:
        items = list(
            self.session.scalars(
                select(CustomerConversation)
                .where(
                    CustomerConversation.business_unit_id == business_unit_id,
                    CustomerConversation.status != "ARCHIVED",
                )
                .order_by(CustomerConversation.updated_at.desc())
                .limit(50)
            ).all()
        )
        total = self.session.scalar(
            select(func.count())
            .select_from(CustomerConversation)
            .where(
                CustomerConversation.business_unit_id == business_unit_id,
                CustomerConversation.status != "ARCHIVED",
            )
        ) or 0
        return CustomerConversationList(
            items=[self.view(item) for item in items],
            total=total,
        )

    def archive_test_conversation(
        self,
        conversation_id: UUID,
    ) -> CustomerConversation:
        conversation = self.get(conversation_id)
        if conversation.status != "ARCHIVED":
            conversation.status = "ARCHIVED"
            conversation.assigned_agent_id = None
            conversation.assigned_at = None
            conversation.version += 1
            self.session.commit()
            self.session.refresh(conversation)
        return conversation

    def archive_test_conversations(
        self,
        *,
        business_unit_id: str,
        requester_prefix: str,
    ) -> int:
        conversations = list(
            self.session.scalars(
                select(CustomerConversation).where(
                    CustomerConversation.business_unit_id == business_unit_id,
                    CustomerConversation.requester_ref.like(
                        f"{requester_prefix}%"
                    ),
                    CustomerConversation.status != "ARCHIVED",
                )
            ).all()
        )
        for conversation in conversations:
            conversation.status = "ARCHIVED"
            conversation.assigned_agent_id = None
            conversation.assigned_at = None
            conversation.version += 1
        self.session.commit()
        return len(conversations)

    def takeover(
        self,
        conversation_id: UUID,
        *,
        expected_version: int,
        agent_id: str,
    ) -> CustomerConversation:
        """Assign the conversation to a human and cancel in-flight turns.

        The turn cancellation locks rows a worker may be finishing at the same
        moment, and PostgreSQL resolves that lock cycle by aborting one side
        (SQLSTATE 40P01). ``run_with_deadlock_retry`` re-runs the victim in a
        fresh transaction, where the version check is re-read and still rejects
        a stale operator request.
        """
        return run_with_deadlock_retry(
            self.session,
            f"takeover of {conversation_id}",
            lambda: self._takeover_once(
                conversation_id,
                expected_version=expected_version,
                agent_id=agent_id,
            ),
        )

    def _takeover_once(
        self,
        conversation_id: UUID,
        *,
        expected_version: int,
        agent_id: str,
    ) -> CustomerConversation:
        conversation = self.session.scalar(
            select(CustomerConversation)
            .where(CustomerConversation.id == conversation_id)
            .with_for_update()
        )
        if conversation is None:
            return self.get(conversation_id)
        if conversation.version != expected_version:
            raise ApiProblem(
                status_code=409,
                code="CONVERSATION_VERSION_CONFLICT",
                title="Conversation was updated",
                detail="Refresh the conversation before taking it over.",
            )
        if (
            conversation.assigned_agent_id
            and conversation.assigned_agent_id != agent_id
        ):
            raise ApiProblem(
                status_code=409,
                code="CONVERSATION_ALREADY_ASSIGNED",
                title="Conversation already assigned",
                detail=f"Conversation is assigned to {conversation.assigned_agent_id}.",
            )
        assigned_count = self.session.scalar(
            select(func.count())
            .select_from(CustomerConversation)
            .where(
                CustomerConversation.assigned_agent_id == agent_id,
                CustomerConversation.status == "ACTIVE",
                CustomerConversation.business_unit_id
                == conversation.business_unit_id,
            )
        ) or 0
        presence = self.session.scalar(
            select(AgentPresence).where(AgentPresence.agent_id == agent_id)
        )
        capacity = (
            presence.max_conversations
            if presence is not None
            else self.MAX_AGENT_CONVERSATIONS
        )
        if assigned_count >= capacity:
            raise ApiProblem(
                status_code=409,
                code="AGENT_CAPACITY_REACHED",
                title="Agent capacity reached",
                detail=(
                    f"An agent can handle at most "
                    f"{capacity} active conversations."
                ),
            )
        previous_agent_id = conversation.assigned_agent_id
        conversation.assigned_agent_id = agent_id
        conversation.assigned_at = datetime.now(UTC)
        conversation.version += 1
        cancelled_turn_ids = self._cancel_active_turns(
            conversation.id, actor_id=agent_id
        )
        ticket = (
            self.session.get(Ticket, conversation.current_ticket_id)
            if conversation.current_ticket_id is not None
            else None
        )
        if (
            ticket is not None
            and ticket.workflow_state
            in _HUMAN_TAKEOVER_TICKET_STATES
        ):
            # The human now owns the work: the ticket must say so, otherwise
            # the workbench refuses their manual reply.
            transition_ticket(
                self.session,
                ticket,
                WorkflowState.TAKEN_OVER,
                reason_code="HUMAN_TAKEOVER",
                actor_type="USER",
                actor_id=agent_id,
            )
            ticket.status = TicketStatus.IN_PROGRESS
            ticket.needs_human = True
            ticket.human_reason = "HUMAN_TAKEOVER"
            ticket.version += 1
        if previous_agent_id is None:
            # A human takes the conversation from the digital employee. The
            # next turn (after the human hands it back) must inherit what the
            # employee had established, and the replay must show the handover.
            create_handoff(
                self.session,
                conversation=conversation,
                from_turn=latest_turn(self.session, conversation.id),
                to_employee=None,
                kind="HUMAN_TAKEOVER",
                reason_code="MANUAL",
                actor_id=agent_id,
                extra_summary={
                    "taken_over_by": agent_id,
                    "cancelled_turn_ids": [
                        str(turn_id) for turn_id in cancelled_turn_ids
                    ],
                },
                dedupe=False,
            )
        self.session.commit()
        self.session.refresh(conversation)
        return conversation

    def _cancel_active_turns(
        self,
        conversation_id: UUID,
        *,
        actor_id: str,
    ) -> Sequence[UUID]:
        """Cancel turns a human is about to answer instead.

        A digital employee answer produced after takeover would either talk
        over the human or race the human's reply into the outbox. Queued and
        running turns are cancelled together; a turn that already reached a
        terminal status is left untouched.
        """
        turns = list(
            self.session.scalars(
                select(ConversationTurn)
                .where(
                    ConversationTurn.conversation_id == conversation_id,
                    ConversationTurn.status.in_(
                        [TurnStatus.PENDING.value, TurnStatus.RUNNING.value]
                    ),
                )
                .with_for_update()
            ).all()
        )
        cancelled: list[UUID] = []
        for turn in turns:
            transition_turn(
                self.session,
                turn,
                TurnStatus.CANCELLED,
                reason_code="HUMAN_TAKEOVER",
                actor_id=actor_id,
                actor_type="AGENT",
                stage_label="人工已接管",
                payload={"handoff_kind": "HUMAN_TAKEOVER"},
            )
            turn.lease_expires_at = None
            cancelled.append(turn.id)
        return cancelled

    def release(self, conversation_id: UUID, *, agent_id: str) -> CustomerConversation:
        conversation = self.session.scalar(
            select(CustomerConversation)
            .where(CustomerConversation.id == conversation_id)
            .with_for_update()
        )
        if conversation is None:
            return self.get(conversation_id)
        if conversation.assigned_agent_id not in {None, agent_id}:
            raise ApiProblem(
                status_code=409,
                code="CONVERSATION_ASSIGNED_TO_OTHER_AGENT",
                title="Conversation assigned to another agent",
                detail="Only the assigned agent can release this conversation.",
            )
        returning_agent_id = conversation.assigned_agent_id
        conversation.assigned_agent_id = None
        conversation.assigned_at = None
        conversation.version += 1
        if returning_agent_id is not None:
            self._record_human_return(
                conversation,
                agent_id=returning_agent_id,
            )
        self.session.commit()
        self.session.refresh(conversation)
        return conversation

    def _record_human_return(
        self,
        conversation: CustomerConversation,
        *,
        agent_id: str,
        human_message: CustomerMessage | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Record that the human handed the conversation back.

        The employee that resumes must know a person answered in the
        meantime; otherwise the next turn reasons from its own older answer.
        """
        employee = (
            self.session.get(DigitalEmployee, conversation.employee_id)
            if conversation.employee_id is not None
            else None
        )
        create_handoff(
            self.session,
            conversation=conversation,
            from_turn=latest_turn(self.session, conversation.id),
            to_employee=employee,
            kind="HUMAN_RETURN",
            reason_code="MANUAL",
            actor_id=agent_id,
            correlation_id=correlation_id,
            human_message=human_message or latest_human_message(
                self.session, conversation.id
            ),
            extra_summary={"returned_by": agent_id},
            dedupe=False,
        )

    def send_manual_reply(
        self,
        conversation_id: UUID,
        payload: CustomerManualReplyCreate,
        *,
        agent_id: str,
        correlation_id: str,
    ) -> CustomerConversation:
        """Send a human reply; a lost deadlock retries in a fresh transaction."""
        return run_with_deadlock_retry(
            self.session,
            f"manual reply on {conversation_id}",
            lambda: self._send_manual_reply_once(
                conversation_id,
                payload,
                agent_id=agent_id,
                correlation_id=correlation_id,
            ),
        )

    def _send_manual_reply_once(
        self,
        conversation_id: UUID,
        payload: CustomerManualReplyCreate,
        *,
        agent_id: str,
        correlation_id: str,
    ) -> CustomerConversation:
        conversation = self.session.scalar(
            select(CustomerConversation)
            .where(CustomerConversation.id == conversation_id)
            .with_for_update()
        )
        if conversation is None:
            return self.get(conversation_id)
        if conversation.assigned_agent_id != agent_id:
            raise ApiProblem(
                status_code=409,
                code="CONVERSATION_NOT_ASSIGNED_TO_AGENT",
                title="Conversation is not assigned to this agent",
                detail="Take over the conversation before sending a manual reply.",
            )
        ticket = (
            self.session.scalar(
                select(Ticket)
                .where(Ticket.id == conversation.current_ticket_id)
                .with_for_update()
            )
            if conversation.current_ticket_id
            else None
        )
        if ticket is None:
            raise ApiProblem(
                status_code=409,
                code="CONVERSATION_TICKET_NOT_FOUND",
                title="Conversation has no current ticket",
                detail="A manual reply requires an active conversation ticket.",
            )
        if ticket.workflow_state not in {
            WorkflowState.PENDING_REVIEW,
            WorkflowState.NEEDS_HUMAN,
            WorkflowState.TAKEN_OVER,
        }:
            raise ApiProblem(
                status_code=409,
                code="CONVERSATION_NOT_AWAITING_HUMAN",
                title="Conversation is not awaiting human handling",
                detail="The current ticket has already completed or is syncing.",
            )
        content = payload.content.strip()
        reply_sequence = self._next_sequence(conversation.id)
        reply_message = CustomerMessage(
            conversation_id=conversation.id,
            sequence=reply_sequence,
            role="ASSISTANT",
            content=content,
            ticket_id=ticket.id,
            created_by=agent_id,
        )
        self.session.add(reply_message)
        self.session.flush()
        conversation.version += 1
        if payload.resolve:
            previous_state = ticket.workflow_state
            ticket.workflow_state = WorkflowState.COMPLETED
            ticket.status = TicketStatus.RESOLVED
            ticket.needs_human = False
            ticket.human_reason = None
            ticket.version += 1
            conversation.assigned_agent_id = None
            conversation.assigned_at = None
            self.session.add(
                CustomerMessage(
                    conversation_id=conversation.id,
                    sequence=reply_sequence + 1,
                    role="ASSISTANT",
                    content=(
                        "人工处理已完成，会话已交还数字员工。"
                        "后续问题将继续由数字员工接待。"
                    ),
                    ticket_id=ticket.id,
                    created_by="digital_employee",
                )
            )
            self._record_human_return(
                conversation,
                agent_id=agent_id,
                human_message=reply_message,
                correlation_id=correlation_id,
            )
            self.session.add(
                WorkflowTransition(
                    ticket_id=ticket.id,
                    from_state=previous_state,
                    to_state=WorkflowState.COMPLETED,
                    reason_code="MANUAL_RESOLUTION",
                    actor_type="USER",
                    actor_id=agent_id,
                )
            )
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="customer_service.manual_reply",
            actor_type="USER",
            actor_id=agent_id,
            resource_type="customer_conversation",
            resource_id=conversation.id,
            action="manual_reply",
            decision="EXECUTED",
            payload={
                "ticket_id": str(ticket.id),
                "resolved": payload.resolve,
                "content_length": len(content),
            },
        )
        if conversation.external_connector_id is not None:
            from ticket_agent.connectors.models import ExternalConnector
            from ticket_agent.connectors.outbound import (
                enqueue_conversation_reply,
            )

            connector = self.session.get(
                ExternalConnector,
                conversation.external_connector_id,
            )
            if connector is not None:
                enqueue_conversation_reply(
                    self.session,
                    connector=connector,
                    conversation=conversation,
                    content=content,
                    idempotency_key=(
                        f"manual:{conversation.id}:{reply_sequence}"
                    ),
                    correlation_id=correlation_id,
                )
        self.session.commit()
        self.session.refresh(conversation)
        return conversation

    def view(
        self,
        conversation: CustomerConversation,
        *,
        replayed: bool = False,
    ) -> CustomerConversationView:
        ticket = (
            self.session.get(Ticket, conversation.current_ticket_id)
            if conversation.current_ticket_id
            else None
        )
        current_turn = self.session.scalar(
            select(ConversationTurn)
            .where(ConversationTurn.conversation_id == conversation.id)
            .order_by(ConversationTurn.sequence.desc())
            .limit(1)
        )
        last_handoff = self.session.scalar(
            select(ConversationHandoff)
            .where(ConversationHandoff.conversation_id == conversation.id)
            .order_by(ConversationHandoff.created_at.desc())
            .limit(1)
        )
        return CustomerConversationView(
            id=conversation.id,
            business_unit_id=conversation.business_unit_id,
            service_entry_id=conversation.service_entry_id,
            employee_id=conversation.employee_id,
            employee_source=conversation.employee_source,
            employee_locked_at=conversation.employee_locked_at,
            requester_ref=conversation.requester_ref,
            category_name=conversation.category_name,
            category_profile_id=conversation.category_profile_id,
            channel=conversation.channel,
            status=conversation.status,
            current_ticket_id=conversation.current_ticket_id,
            current_workflow_state=ticket.workflow_state if ticket else None,
            current_ticket_status=ticket.status if ticket else None,
            current_risk_level=ticket.risk_level if ticket else None,
            current_priority=ticket.priority if ticket else None,
            current_needs_human=ticket.needs_human if ticket else None,
            assigned_agent_id=conversation.assigned_agent_id,
            assigned_at=conversation.assigned_at,
            version=conversation.version,
            messages=[self.message_view(message) for message in self.messages(conversation.id)],
            current_turn=(
                self.turn_view(current_turn)
                if current_turn is not None
                else None
            ),
            latest_handoff=(
                self.handoff_view(last_handoff)
                if last_handoff is not None
                else None
            ),
            replayed=replayed,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )

    def handoff_view(
        self,
        handoff: ConversationHandoff,
    ) -> ConversationHandoffView:
        names: dict[UUID, str] = {}
        employee_ids = [
            employee_id
            for employee_id in (
                handoff.from_employee_id,
                handoff.to_employee_id,
            )
            if employee_id is not None
        ]
        if employee_ids:
            names = {
                employee_id: name
                for employee_id, name in self.session.execute(
                    select(DigitalEmployee.id, DigitalEmployee.name).where(
                        DigitalEmployee.id.in_(employee_ids)
                    )
                ).all()
            }
        return ConversationHandoffView(
            id=handoff.id,
            conversation_id=handoff.conversation_id,
            from_turn_id=handoff.from_turn_id,
            to_turn_id=handoff.to_turn_id,
            from_employee_id=handoff.from_employee_id,
            to_employee_id=handoff.to_employee_id,
            from_employee_name=(
                names.get(handoff.from_employee_id)
                if handoff.from_employee_id
                else None
            ),
            to_employee_name=(
                names.get(handoff.to_employee_id)
                if handoff.to_employee_id
                else None
            ),
            kind=handoff.kind,
            reason_code=handoff.reason_code,
            summary=dict(handoff.summary_json or {}),
            created_by=handoff.created_by,
            created_at=handoff.created_at,
        )

    def switch_employee(
        self,
        conversation_id: UUID,
        *,
        employee_id: UUID,
        reason: str | None,
        principal: Principal,
        correlation_id: str,
    ) -> tuple[CustomerConversation, ConversationHandoff]:
        """Hand a conversation to another digital employee and record it.

        The handoff appends a turn event, which serialises against a worker
        finishing the same turn; the pair can deadlock and the loser is
        retried in a fresh transaction.
        """
        return run_with_deadlock_retry(
            self.session,
            f"employee switch of {conversation_id}",
            lambda: self._switch_employee_once(
                conversation_id,
                employee_id=employee_id,
                reason=reason,
                principal=principal,
                correlation_id=correlation_id,
            ),
        )

    def _switch_employee_once(
        self,
        conversation_id: UUID,
        *,
        employee_id: UUID,
        reason: str | None,
        principal: Principal,
        correlation_id: str,
    ) -> tuple[CustomerConversation, ConversationHandoff]:
        conversation = self.session.scalar(
            select(CustomerConversation)
            .where(CustomerConversation.id == conversation_id)
            .with_for_update()
        )
        if conversation is None:
            raise ApiProblem(
                status_code=404,
                code="CONVERSATION_NOT_FOUND",
                title="Conversation not found",
                detail=f"Conversation {conversation_id} does not exist.",
            )
        employee = self.session.get(DigitalEmployee, employee_id)
        if employee is None:
            raise ApiProblem(
                status_code=404,
                code="EMPLOYEE_NOT_FOUND",
                title="Digital employee not found",
                detail=f"Digital employee {employee_id} does not exist.",
            )
        if employee.status != "ACTIVE":
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_NOT_ACTIVE",
                title="Digital employee is not active",
                detail="A conversation can only be handed to an active employee.",
            )
        if conversation.employee_id == employee.id:
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_UNCHANGED",
                title="Conversation already belongs to this employee",
                detail="Switching to the current employee is a no-op.",
            )
        if conversation.service_entry_id is not None:
            pool = service_entry_employee_ids(
                self.session,
                conversation.service_entry_id,
                business_unit_id=conversation.business_unit_id,
            )
            if pool is None or employee.id not in pool:
                # A conversation that came through an entry belongs to that
                # entry's pool; a manual switch must not smuggle in an
                # employee from another direction.
                raise ApiProblem(
                    status_code=409,
                    code="HANDOFF_EMPLOYEE_OUTSIDE_ENTRY",
                    title="目标员工不在业务入口内",
                    detail=(
                        "该会话来自业务入口，只能转交给入口内已启用的数字员工。"
                    ),
                )
        current_employee = (
            self.session.get(DigitalEmployee, conversation.employee_id)
            if conversation.employee_id
            else None
        )
        required_domain = (
            current_employee.domain if current_employee is not None else "customer_service"
        )
        if employee.domain != required_domain:
            # A customer conversation must stay inside its own domain; a hand
            # off to HR or an operations agent would run the wrong playbook.
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_DOMAIN_MISMATCH",
                title="Digital employee belongs to another domain",
                detail=(
                    "A conversation can only be handed to an employee of its "
                    f"own domain ({required_domain})."
                ),
            )
        from_turn = latest_turn(self.session, conversation.id)
        handoff = create_handoff(
            self.session,
            conversation=conversation,
            from_turn=from_turn,
            to_employee=employee,
            kind="OPERATOR_SWITCH",
            reason_code="MANUAL",
            actor_id=principal.actor_id,
            correlation_id=correlation_id,
        )
        if reason:
            summary = dict(handoff.summary_json)
            summary["operator_reason"] = reason
            handoff.summary_json = summary
        conversation.employee_id = employee.id
        # A supervisor decided; the entry router must not take the
        # conversation back on the next ambiguous message.
        conversation.employee_source = "MANUAL"
        conversation.employee_locked_at = datetime.now(UTC)
        conversation.reroute_candidate_id = None
        conversation.reroute_streak = 0
        conversation.version += 1
        ticket = (
            self.session.get(Ticket, conversation.current_ticket_id)
            if conversation.current_ticket_id
            else None
        )
        if ticket is not None:
            ticket.employee_id = employee.id
            ticket.version += 1
            self.session.add(
                WorkflowTransition(
                    ticket_id=ticket.id,
                    from_state=ticket.workflow_state,
                    to_state=ticket.workflow_state,
                    reason_code="EMPLOYEE_SWITCHED",
                    actor_type="USER",
                    actor_id=principal.actor_id,
                )
            )
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="customer_service.conversation.employee_switched",
            actor_type="USER",
            actor_id=principal.actor_id,
            resource_type="customer_conversation",
            resource_id=conversation.id,
            action="switch_employee",
            decision="EXECUTED",
            reason_code="MANUAL",
            payload={
                "handoff_id": str(handoff.id),
                "from_employee_id": (
                    str(handoff.from_employee_id)
                    if handoff.from_employee_id
                    else None
                ),
                "to_employee_id": str(employee.id),
                "reason": reason,
            },
        )
        self.session.commit()
        self.session.refresh(conversation)
        return conversation, handoff

    def message_view(self, message: CustomerMessage) -> CustomerMessageView:
        return CustomerMessageView(
            id=message.id,
            sequence=message.sequence,
            role=message.role,
            content=message.content,
            ticket_id=message.ticket_id,
            turn_id=message.turn_id,
            created_by=message.created_by,
            created_at=message.created_at,
        )

    def turn_view(self, turn: ConversationTurn) -> ConversationTurnView:
        return ConversationTurnView(
            id=turn.id,
            conversation_id=turn.conversation_id,
            ticket_id=turn.ticket_id,
            sequence=turn.sequence,
            status=turn.status,
            stage_label=turn.stage_label,
            employee_id=turn.employee_id,
            employee_config_revision=turn.employee_config_revision,
            correlation_id=turn.correlation_id,
            version=turn.version,
            attempt_count=turn.attempt_count,
            handoff_id=turn.handoff_id,
            intent=turn.intent,
            analysis=turn.analysis_json,
            response_provider=turn.response_provider,
            response_model=turn.response_model,
            grounding_status=turn.grounding_status,
            gate=turn.gate_json,
            citations=turn.citations_json,
            trace=turn.trace_json,
            tool_calls=turn.tool_calls_json,
            error_code=turn.error_code,
            error_message=turn.error_message,
            started_at=turn.started_at,
            completed_at=turn.completed_at,
            created_at=turn.created_at,
        )

    def append_assistant_message(
        self,
        *,
        conversation_id: UUID,
        ticket_id: UUID | None,
        content: str,
        created_by: str = "digital_employee",
        turn_id: UUID | None = None,
    ) -> CustomerMessage:
        message = CustomerMessage(
            conversation_id=conversation_id,
            sequence=self._next_sequence(conversation_id),
            role="ASSISTANT",
            content=content,
            ticket_id=ticket_id,
            turn_id=turn_id,
            created_by=created_by,
        )
        self.session.add(message)
        self.session.flush()
        return message

    def complete_turn(
        self,
        *,
        turn_id: UUID,
        assistant_message: CustomerMessage,
        response_provider: str,
        response_model: str,
        grounding_status: str,
        citations: Sequence[dict[str, Any]],
        trace: Sequence[str],
        tool_calls: Sequence[dict[str, Any]],
        intent: str | None,
        analysis: dict[str, Any],
        skill_snapshot: dict[str, Any] | None = None,
        completion: dict[str, Any] | None = None,
        gate: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        actor_id: str = "digital_employee.runtime",
    ) -> ConversationTurn:
        turn = self.session.scalar(
            select(ConversationTurn)
            .where(ConversationTurn.id == turn_id)
            .with_for_update()
        )
        if turn is None:
            raise ApiProblem(
                status_code=404,
                code="CONVERSATION_TURN_NOT_FOUND",
                title="Conversation turn not found",
                detail=f"Conversation turn {turn_id} does not exist.",
            )
        if parse_turn_status(turn.status) is TurnStatus.CANCELLED:
            # A human took over while this answer was being generated. The
            # assistant message was already flushed in this transaction; the
            # caller rolls back so neither the reply nor its events survive.
            raise ApiProblem(
                status_code=409,
                code="TURN_CANCELLED",
                title="Turn was cancelled",
                detail="A human took over the conversation during this turn.",
            )
        if skill_snapshot is not None:
            turn.skill_code = str(skill_snapshot.get("code") or "") or None
            raw_version = skill_snapshot.get("definition_version")
            turn.skill_version = (
                int(raw_version)
                if isinstance(raw_version, int)
                else None
            )
            turn.skill_snapshot_json = jsonable_encoder(skill_snapshot)
            record_turn_event(
                self.session,
                turn,
                event_type="SKILL_SELECTED",
                actor_id=actor_id,
                correlation_id=correlation_id,
                payload={
                    "skill_code": turn.skill_code,
                    "skill_version": turn.skill_version,
                    "contract_present": (
                        skill_snapshot.get("definition") is not None
                    ),
                    "match_reason": skill_snapshot.get("match_reason"),
                },
            )
        if completion is not None:
            turn.completion_json = jsonable_encoder(completion)
            record_turn_event(
                self.session,
                turn,
                event_type="COMPLETION_EVALUATED",
                actor_id=actor_id,
                correlation_id=correlation_id,
                payload={
                    "skill_code": turn.skill_code,
                    "complete": bool(completion.get("complete")),
                    "incomplete_required": completion.get(
                        "incomplete_required", []
                    ),
                    "criteria": completion.get("criteria", {}),
                },
            )
        if gate is not None:
            # The gate verdict is frozen onto the turn so auto-send and later
            # audits read the same decision instead of re-deriving it.
            turn.gate_json = jsonable_encoder(gate)
            record_turn_event(
                self.session,
                turn,
                event_type="GATE_EVALUATED",
                actor_id=actor_id,
                correlation_id=correlation_id,
                payload={
                    "decision": gate.get("decision"),
                    "reasons": gate.get("reasons", []),
                    "version": gate.get("version"),
                    "checks": gate.get("checks", {}),
                },
            )
        # A required Skill step that did not happen must not read as a finished
        # answer. The reply is still recorded, but the turn goes to a human.
        incomplete_skill = (
            completion is not None and not bool(completion.get("complete"))
        )
        transition_turn(
            self.session,
            turn,
            (
                TurnStatus.NEEDS_HUMAN
                if incomplete_skill
                else TurnStatus.COMPLETED
            ),
            reason_code=(
                "SKILL_COMPLETION_INCOMPLETE"
                if incomplete_skill
                else "ANSWER_PRODUCED"
            ),
            actor_id=actor_id,
            correlation_id=correlation_id,
            stage_label=(
                "需人工确认执行步骤" if incomplete_skill else "回答已完成"
            ),
            payload={
                "grounding_status": grounding_status,
                "citation_count": len(citations),
                "tool_call_count": len(tool_calls),
                "provider": response_provider,
                "model": response_model,
                "skill_complete": (
                    bool(completion.get("complete"))
                    if completion is not None
                    else None
                ),
                "gate_decision": gate.get("decision") if gate else None,
            },
        )
        turn.lease_expires_at = None
        turn.assistant_message_id = assistant_message.id
        turn.response_provider = response_provider
        turn.response_model = response_model
        turn.grounding_status = grounding_status
        turn.citations_json = jsonable_encoder(list(citations))
        turn.trace_json = list(trace)
        turn.tool_calls_json = jsonable_encoder(list(tool_calls))
        turn.intent = intent
        turn.analysis_json = analysis
        turn.completed_at = datetime.now(UTC)
        user_message = self.session.get(
            CustomerMessage,
            turn.user_message_id,
        )
        self._update_memory(
            turn.conversation_id,
            turn.sequence,
            user_message.content if user_message else "",
            assistant_message.content,
            turn_id=turn.id,
        )
        self.session.commit()
        return turn

    def _update_memory(
        self,
        conversation_id: UUID,
        turn_sequence: int,
        user_content: str,
        assistant_content: str,
        *,
        turn_id: UUID | None = None,
    ) -> None:
        memory = self.session.get(ConversationMemory, conversation_id)
        previous_summary = memory.summary if memory is not None else ""
        line = (
            f"第 {turn_sequence} 轮 用户：{user_content.strip()[:500]} "
            f"客服：{assistant_content.strip()[:800]}"
        )
        summary = f"{previous_summary}\n{line}".strip()[-4000:]
        source_turn_id = str(turn_id) if turn_id is not None else None
        updated_at = datetime.now(UTC).isoformat()
        facts: dict[str, dict[str, object]] = {}
        repository = repository_name(user_content)
        if repository is None:
            for previous_line in reversed(previous_summary.splitlines()):
                repository = repository_name(previous_line)
                if repository is not None:
                    break
        if repository is not None and repository.casefold() != "owner/repo":
            facts["repository"] = {
                "value": repository,
                "status": "confirmed",
                "source_turn_id": source_turn_id,
                "updated_at": updated_at,
            }
        order_id = _first_match(
            r"(\b[A-Z]{2,}(?:-[A-Z0-9]+){1,}\b)",
            user_content,
        )
        if order_id is not None:
            facts["order_id"] = {
                "value": order_id,
                "status": "confirmed",
                "source_turn_id": source_turn_id,
                "updated_at": updated_at,
            }
        record_memory_turn(
            self.session,
            conversation_id=conversation_id,
            turn_sequence=turn_sequence,
            summary=summary,
            facts=facts,
        )

    def _next_sequence(self, conversation_id: UUID) -> int:
        current = self.session.scalar(
            select(func.max(CustomerMessage.sequence)).where(
                CustomerMessage.conversation_id == conversation_id
            )
        ) or 0
        return int(current) + 1

    def _next_turn_sequence(self, conversation_id: UUID) -> int:
        current = self.session.scalar(
            select(func.max(ConversationTurn.sequence)).where(
                ConversationTurn.conversation_id == conversation_id
            )
        ) or 0
        return int(current) + 1

    def _maybe_reroute_employee(
        self,
        *,
        conversation: CustomerConversation,
        ticket: Ticket,
        content: str,
        turn_sequence: int,
        correlation_id: str,
    ) -> str | None:
        """Move an existing conversation to another employee, if justified.

        The employee is the conversation's owner, not a per-message choice. A
        single message that merely resembles another employee's topics must not
        change who the buyer is talking to; a move needs a margin, a genuine
        capability gap and either an explicit request, a finished ticket, a
        large gap or the same recommendation on several consecutive messages.
        Returns the handoff reason when the conversation moved.
        """
        if conversation.assigned_agent_id is not None:
            # A human owns the conversation. Routing must not move it to
            # another employee underneath them.
            return None
        if conversation.service_entry_id is None:
            return None
        current_employee = (
            self.session.get(DigitalEmployee, conversation.employee_id)
            if conversation.employee_id is not None
            else (
                self.session.get(DigitalEmployee, ticket.employee_id)
                if ticket.employee_id is not None
                else None
            )
        )
        if current_employee is None:
            return None
        if conversation.employee_locked_at is not None:
            # A supervisor chose this employee; the router may not override it.
            self._clear_reroute_evidence(conversation)
            return None
        allowed_employee_ids = TicketService(
            self.session
        )._service_entry_employee_ids(
            conversation.service_entry_id,
            business_unit_id=conversation.business_unit_id,
        )
        route_result = DigitalEmployeeRouter(self.session).route_text(
            business_unit_id=conversation.business_unit_id,
            subject=content.strip().splitlines()[0][:120],
            body=content.strip(),
            channel=conversation.channel,
            allowed_employee_ids=allowed_employee_ids,
            current_employee_id=current_employee.id,
        )
        decision = route_result.decision
        if decision is not None:
            decision.ticket_id = ticket.id
            decision.conversation_id = conversation.id
        assessment = route_result.assessment

        if (
            current_employee.status != "ACTIVE"
            and route_result.employee.id != current_employee.id
        ):
            # A disabled employee cannot keep the conversation, no matter how
            # sticky the routing policy is.
            return self._apply_reroute(
                conversation=conversation,
                ticket=ticket,
                employee=route_result.employee,
                reason_code="CAPABILITY_GAP",
                decision=decision,
                turn_sequence=turn_sequence,
                correlation_id=correlation_id,
                explicit=True,
            )

        if (
            allowed_employee_ids is not None
            and current_employee.id not in allowed_employee_ids
            and route_result.employee.id != current_employee.id
        ):
            # The entry's pool no longer offers the current employee.
            return self._apply_reroute(
                conversation=conversation,
                ticket=ticket,
                employee=route_result.employee,
                reason_code="ENTRY_SCOPE_CHANGED",
                decision=decision,
                turn_sequence=turn_sequence,
                correlation_id=correlation_id,
                explicit=True,
            )

        if assessment is None:
            self._clear_reroute_evidence(conversation)
            self._pin_decision_to_current(decision, current_employee)
            return None

        explicit = explicit_employee_request(content)
        evidence = assessment.margin_met and assessment.capability_gap
        if evidence:
            self._remember_reroute_candidate(
                conversation,
                assessment.candidate_employee_id,
            )
        else:
            self._clear_reroute_evidence(conversation)

        settings = get_settings()
        reason_code: str | None = None
        if explicit:
            reason_code = "EXPLICIT_REQUEST"
        elif evidence and assessment.strong_gap:
            reason_code = "CAPABILITY_GAP"
        elif (
            evidence
            and ticket.workflow_state == WorkflowState.COMPLETED
        ):
            # A finished ticket is a natural boundary: the next question may
            # start with another employee.
            reason_code = "TOPIC_CHANGED"
        elif (
            evidence
            and conversation.reroute_streak
            >= settings.conversation_reroute_min_streak
        ):
            reason_code = "SUSTAINED_TOPIC"

        if reason_code is None:
            self._pin_decision_to_current(decision, current_employee)
            return None

        if not explicit:
            if (
                conversation.auto_reroute_count
                >= settings.conversation_reroute_max_per_conversation
            ):
                self._clear_reroute_evidence(conversation)
                self._pin_decision_to_current(decision, current_employee)
                return None
            last_turn = conversation.last_auto_reroute_turn_sequence
            if (
                last_turn is not None
                and turn_sequence - last_turn
                < settings.conversation_reroute_cooldown_turns
            ):
                # Too soon: keep the current employee but keep the streak, so
                # the move still happens once the cooldown ends.
                self._pin_decision_to_current(decision, current_employee)
                return None

        candidate = (
            self.session.get(
                DigitalEmployee,
                assessment.candidate_employee_id,
            )
            if assessment.candidate_employee_id is not None
            else None
        )
        if candidate is None or candidate.status != "ACTIVE":
            self._pin_decision_to_current(decision, current_employee)
            return None
        return self._apply_reroute(
            conversation=conversation,
            ticket=ticket,
            employee=candidate,
            reason_code=reason_code,
            decision=decision,
            turn_sequence=turn_sequence,
            correlation_id=correlation_id,
            explicit=explicit,
        )

    def _apply_reroute(
        self,
        *,
        conversation: CustomerConversation,
        ticket: Ticket,
        employee: DigitalEmployee,
        reason_code: str,
        decision: DigitalEmployeeRouteDecision | None,
        turn_sequence: int,
        correlation_id: str,
        explicit: bool,
    ) -> str:
        previous_employee_id = conversation.employee_id or ticket.employee_id
        conversation.employee_id = employee.id
        conversation.employee_source = "AUTO_HANDOFF"
        ticket.employee_id = employee.id
        if not explicit:
            conversation.auto_reroute_count += 1
            conversation.last_auto_reroute_turn_sequence = turn_sequence
        conversation.reroute_candidate_id = None
        conversation.reroute_streak = 0
        if decision is not None:
            decision.selected_employee_id = employee.id
            decision.selected_employee_key = employee.employee_key
            decision.reason_code = reason_code
            candidates = list(decision.candidates_json or [])
            for candidate in candidates:
                if isinstance(candidate, dict):
                    candidate["selected"] = (
                        candidate.get("employee_id") == str(employee.id)
                    )
            decision.candidates_json = candidates
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="customer_service.conversation.rerouted",
            actor_type="SERVICE",
            actor_id="digital_employee.router",
            resource_type="customer_conversation",
            resource_id=conversation.id,
            action="route",
            decision="EXECUTED",
            reason_code=reason_code,
            payload={
                "ticket_id": str(ticket.id),
                "previous_employee_id": (
                    str(previous_employee_id)
                    if previous_employee_id is not None
                    else None
                ),
                "employee_id": str(employee.id),
                "employee_key": employee.employee_key,
            },
        )
        return reason_code

    @staticmethod
    def _remember_reroute_candidate(
        conversation: CustomerConversation,
        candidate_id: UUID | None,
    ) -> None:
        if candidate_id is None:
            conversation.reroute_candidate_id = None
            conversation.reroute_streak = 0
            return
        if conversation.reroute_candidate_id == candidate_id:
            conversation.reroute_streak += 1
            return
        conversation.reroute_candidate_id = candidate_id
        conversation.reroute_streak = 1

    @staticmethod
    def _clear_reroute_evidence(conversation: CustomerConversation) -> None:
        conversation.reroute_candidate_id = None
        conversation.reroute_streak = 0

    @staticmethod
    def _pin_decision_to_current(
        decision: DigitalEmployeeRouteDecision | None,
        employee: DigitalEmployee,
    ) -> None:
        """Record that the router kept the conversation where it was."""
        if decision is None:
            return
        decision.selected_employee_id = employee.id
        decision.selected_employee_key = employee.employee_key
        candidates = list(decision.candidates_json or [])
        for candidate in candidates:
            if isinstance(candidate, dict):
                candidate["selected"] = (
                    candidate.get("employee_id") == str(employee.id)
                )
        decision.candidates_json = candidates
        decision.reason_code = "STICKY_CURRENT"
        decision.reason = (
            "问题更像其他员工，但会话继续由当前员工处理；"
            "需要连续同向信号、明确要求或能力缺口才会转接。"
        )

    def _conversation_initial_ticket(
        self,
        conversation: CustomerConversation,
        source_system: str,
    ) -> Ticket | None:
        """Return the initial ticket another message of this conversation made.

        The conversation's first message opens a ticket whose source id is
        derived from the conversation, so the ticket can be found before
        ``current_ticket_id`` is committed.
        """
        return self.session.scalar(
            select(Ticket).where(
                Ticket.source_system == source_system,
                Ticket.source_ticket_id == f"CONV-{conversation.id}-initial",
            )
        )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _first_match(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1) if match else None


def _integer_value(value: object) -> int:
    return value if isinstance(value, int) else 0


def _risk_rank(level: str | None) -> int:
    return {"R0": 0, "R1": 1, "R2": 2, "R3": 3}.get(level or "R1", 1)


def _required_skill(ticket: Ticket | None) -> str | None:
    if ticket is None:
        return None
    category = ticket.category_primary
    if category in {"ecommerce_presales", "ecommerce_aftersales"}:
        return category
    if category in {"transaction_dispute", "complaint_escalation"}:
        return "ecommerce_aftersales"
    if ticket.subject and any(
        keyword in ticket.subject.lower()
        for keyword in ("物流", "快递", "运单", "发货")
    ):
        return "logistics"
    return None


def _small_talk_reply(
    content: str,
    *,
    enterprise_service: bool,
    kind: SmallTalkKind | None,
    employee: DigitalEmployee | None,
    memory: MemorySnapshot | None = None,
) -> str | None:
    del content
    if kind is None:
        return None
    if kind == "thanks":
        return "不客气，还有其他问题可以继续问我。"
    if kind == "farewell":
        return "再见，有需要随时回来。"
    if kind == "clarification":
        return (
            "可以。请说明你遇到的具体问题、涉及的对象和期望结果；"
            "如果是研发仓库问题，请提供 owner/repo 格式的公开仓库。"
        )
    if kind == "greeting":
        order_fact = (
            memory.facts.get("order_id") if memory is not None else None
        )
        order_id = order_fact.get("value") if order_fact else None
        if order_id:
            # The buyer came back to an order this conversation already
            # confirmed. A generic self-introduction would drop that memory.
            name = f"我是{employee.name}。" if employee is not None else ""
            return (
                f"你好，{name}我记得你在跟进订单 {order_id}，"
                "需要继续处理哪一步？"
            )
    return _employee_introduction(
        employee=employee,
        enterprise_service=enterprise_service,
    )


def _employee_introduction(
    *,
    employee: DigitalEmployee | None,
    enterprise_service: bool,
) -> str:
    if employee is not None:
        employee_text = (
            f"{employee.name} {employee.employee_key} "
            f"{employee.template_code or ''}"
        ).casefold()
        capabilities = employee.manifest_json.get("capabilities", [])
        capability_text = "、".join(
            str(item)
            for item in capabilities
            if isinstance(item, str) and item.strip()
        )
        if any(term in employee_text for term in ("研发", "developer")):
            return (
                f"我是{employee.name}。我可以查询公开 GitHub 仓库的文档结构、"
                "模块职责和依赖关系；回答会说明知识或只读工具依据。"
                "私有仓库、密钥和访问令牌不会读取。"
            )
        if employee.template_code == "enterprise_service_desk":
            return (
                f"我是{employee.name}。我可以处理企业制度、账号、IT、流程和"
                "工单问题；研发仓库文档问题会交给研发支持员工。"
                "涉及权限、隐私、资金或外部写操作时会转人工确认。"
            )
        if capabilities:
            return (
                f"我是{employee.name}。我可以处理：{capability_text}。"
                "我会优先依据已发布知识和获准工具回答；没有依据时会明确说明。"
            )
        return (
            f"我是{employee.name}。请描述你的具体问题，我会先识别问题类型，"
            "再选择相应知识、工具或人工处理。"
        )
    if enterprise_service:
        return (
            "我是企业服务台数字员工。你可以咨询制度、账号、IT、流程、"
            "工单或公开仓库文档问题；我会根据问题自动选择专业员工。"
        )
    return "我是数字员工。你可以咨询商品、物流、售后或业务办理问题。"

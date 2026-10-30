"""M4: replay, retry and operations views over the conversation runtime.

Covers the operator-facing surface built on the turn log: the turn list and
detail, event pagination, the handoff list, retrying a retryable turn, the
operations turn list and runtime health metrics, plus the two behaviour fixes
this milestone depends on (RT-30 takeover cancels live turns, RT-07 ticket
body is the current question only).
"""

import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from ticket_agent.customer_service.context import assemble_context
from ticket_agent.customer_service.models import (
    ConversationTurn,
    ConversationTurnEvent,
    CustomerConversation,
    CustomerMessage,
)
from ticket_agent.customer_service.service import CustomerConversationService
from ticket_agent.customer_service.turns import (
    ConversationTurnOrchestrator,
    process_conversation_turn,
)
from ticket_agent.shared.db import SessionLocal
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import get_settings
from ticket_agent.tickets.domain import WorkflowState
from ticket_agent.tickets.models import Ticket, TicketStatus

ADMIN = {"X-Actor-Id": "admin-1", "X-Actor-Role": "admin"}
AGENT = {"X-Actor-Id": "agent-1", "X-Actor-Role": "agent"}
SUPERVISOR = {"X-Actor-Id": "supervisor-1", "X-Actor-Role": "supervisor"}
REQUESTER = {"X-Actor-Id": "buyer-1", "X-Actor-Role": "requester"}


def _employee(client: TestClient, key: str, name: str) -> str:
    response = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json={
            "employee_key": key,
            "name": name,
            "version": "1.0.0",
            "scenario_type": "customer_service_ticket",
            "workflow_key": "customer_service_ticket_v1",
            "business_unit_id": "bu_demo",
            "service_identity": f"digital_employee.{key}",
            "handoff_queue": "MANUAL_TRIAGE",
            "tool_allowlist": ["ticket.read", "knowledge.search", "draft.create"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _conversation(
    client: TestClient,
    *,
    requester_ref: str,
    employee_id: str | None = None,
) -> str:
    payload: dict[str, object] = {
        "business_unit_id": "bu_demo",
        "requester_ref": requester_ref,
        "channel": "enterprise_service",
    }
    if employee_id is not None:
        payload["employee_id"] = employee_id
    response = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _send(
    client: TestClient,
    conversation_id: str,
    content: str,
    *,
    client_message_id: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"content": content}
    if client_message_id is not None:
        payload["client_message_id"] = client_message_id
    response = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/messages",
        headers=AGENT,
        json=payload,
    )
    assert response.status_code == 202, response.text
    return dict(response.json())


def _small_talk_turn(
    client: TestClient,
    *,
    employee_id: str | None = None,
) -> tuple[str, str]:
    conversation_id = _conversation(
        client,
        requester_ref=f"replay-buyer-{uuid4().hex[:8]}",
        employee_id=employee_id,
    )
    accepted = _send(client, conversation_id, "你好")
    return conversation_id, str(accepted["current_turn"]["id"])


def _force_turn_status(
    turn_id: str,
    status: str,
    *,
    attempt_count: int = 1,
    lease_offset_seconds: int = 60,
) -> None:
    with SessionLocal() as session:
        turn = session.get(ConversationTurn, UUID(turn_id))
        assert turn is not None
        turn.status = status
        turn.attempt_count = attempt_count
        turn.lease_expires_at = datetime.now(UTC) + timedelta(
            seconds=lease_offset_seconds
        )
        session.commit()


def _force_ticket_completed(ticket_id: str) -> None:
    """Park a ticket in the finished state without replaying the whole flow.

    The ticket state machine is still exercised afterwards: the buyer's next
    message and the human reply go through the real service endpoints.
    """
    with SessionLocal() as session:
        ticket = session.get(Ticket, UUID(ticket_id))
        assert ticket is not None
        ticket.workflow_state = WorkflowState.COMPLETED
        ticket.status = TicketStatus.RESOLVED
        ticket.needs_human = False
        ticket.human_reason = None
        session.commit()


def _turn_events(turn_id: str) -> list[ConversationTurnEvent]:
    with SessionLocal() as session:
        return list(
            session.scalars(
                select(ConversationTurnEvent)
                .where(ConversationTurnEvent.turn_id == UUID(turn_id))
                .order_by(ConversationTurnEvent.sequence)
            )
        )


def _conversation_messages(conversation_id: str) -> list[CustomerMessage]:
    with SessionLocal() as session:
        return list(
            session.scalars(
                select(CustomerMessage)
                .where(CustomerMessage.conversation_id == UUID(conversation_id))
                .order_by(CustomerMessage.sequence)
            )
        )


def _queue_pending_turn(
    conversation_id: str,
    *,
    employee_id: str,
    content: str,
) -> str:
    """Queue a turn exactly as the API leaves it before a worker claims it."""
    with SessionLocal() as session:
        conversation = session.get(CustomerConversation, UUID(conversation_id))
        assert conversation is not None
        sequence = (
            session.scalar(
                select(func.max(CustomerMessage.sequence)).where(
                    CustomerMessage.conversation_id == conversation.id
                )
            )
            or 0
        ) + 1
        message = CustomerMessage(
            conversation_id=conversation.id,
            sequence=sequence,
            role="BUYER",
            content=content,
            created_by="agent-1",
        )
        session.add(message)
        session.flush()
        turn = ConversationTurn(
            conversation_id=conversation.id,
            sequence=sequence,
            status="PENDING",
            user_message_id=message.id,
            employee_id=UUID(employee_id),
            client_message_id=f"queued-{uuid4().hex[:8]}",
            lease_expires_at=datetime.now(UTC)
            + timedelta(seconds=get_settings().conversation_turn_lease_seconds),
        )
        session.add(turn)
        session.flush()
        message.turn_id = turn.id
        session.commit()
        return str(turn.id)


# --- turn list / detail / events -------------------------------------------


def test_turn_list_and_detail_expose_the_replay_record(
    client: TestClient,
) -> None:
    employee_id = _employee(client, "replay_detail", "回放客服")
    conversation_id, small_talk_turn = _small_talk_turn(
        client, employee_id=employee_id
    )
    # A second turn goes through the orchestrator, which is what records the
    # context snapshot the detail view is meant to expose.
    failed = _send(client, conversation_id, "订单 AB-1001 一直没发货，能查一下吗？")
    failed_turn = str(failed["current_turn"]["id"])
    assert failed_turn != small_talk_turn

    listed = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}/turns",
        headers=AGENT,
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] == 2
    # Newest first.
    assert [item["id"] for item in body["items"]] == [failed_turn, small_talk_turn]
    assert body["items"][0]["status"] == "FAILED_TERMINAL"
    assert body["items"][1]["status"] == "COMPLETED"

    detail = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}"
        f"/turns/{failed_turn}",
        headers=AGENT,
    )
    assert detail.status_code == 200, detail.text
    replay = detail.json()
    assert replay["id"] == failed_turn
    # The detail adds the frozen inputs the list deliberately omits.
    assert replay["context"] is not None
    assert replay["context"]["schema_version"] == 2
    # The small talk fast path wrote a buyer and an assistant message, so the
    # orchestrator turn sees both as history.
    assert replay["context"]["history_sequences"] == [1, 2]
    assert replay["error_code"] == "KNOWLEDGE_NOT_FOUND"
    assert "skill_version" in replay
    assert "completion" in replay
    assert "skill_snapshot" in replay

    small_talk_detail = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}"
        f"/turns/{small_talk_turn}",
        headers=AGENT,
    )
    assert small_talk_detail.status_code == 200
    assert small_talk_detail.json()["gate"]["decision"] == "AUTO_SEND"

    missing = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}"
        f"/turns/{uuid4()}",
        headers=AGENT,
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "CONVERSATION_TURN_NOT_FOUND"

    denied = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}/turns",
        headers=REQUESTER,
    )
    assert denied.status_code == 403

    foreign = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}/turns",
        headers={**AGENT, "X-Business-Units": "bu_other"},
    )
    assert foreign.status_code == 403


def test_turn_events_page_forward_with_after_sequence(
    client: TestClient,
) -> None:
    conversation_id, turn_id = _small_talk_turn(client)
    events_url = (
        f"/api/v1/customer-service/conversations/{conversation_id}"
        f"/turns/{turn_id}/events"
    )

    first = client.get(events_url, headers=AGENT, params={"limit": 2})
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert [event["sequence"] for event in first_body["events"]] == [1, 2]
    # The fast path now assembles context too, so its event log has five
    # entries: created, context, running, gate, completed.
    assert first_body["total"] == 5
    assert first_body["has_more"] is True

    second = client.get(
        events_url,
        headers=AGENT,
        params={"after_sequence": 2, "limit": 2},
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert [event["sequence"] for event in second_body["events"]] == [3, 4]
    assert second_body["total"] == 5
    assert second_body["has_more"] is True

    third = client.get(
        events_url,
        headers=AGENT,
        params={"after_sequence": 4},
    )
    assert third.status_code == 200, third.text
    third_body = third.json()
    assert [event["sequence"] for event in third_body["events"]] == [5]
    assert third_body["has_more"] is False

    past = client.get(events_url, headers=AGENT, params={"after_sequence": 5})
    assert past.status_code == 200
    assert past.json()["events"] == []
    assert past.json()["has_more"] is False

    invalid = client.get(events_url, headers=AGENT, params={"after_sequence": -1})
    assert invalid.status_code == 422


def test_handoff_list_shows_employee_switches(client: TestClient) -> None:
    source = _employee(client, "replay_handoff_source", "原客服")
    target = _employee(client, "replay_handoff_target", "接手客服")
    conversation_id = _conversation(
        client,
        requester_ref="handoff-list-buyer",
        employee_id=source,
    )
    _send(client, conversation_id, "你好")

    switched = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/employee",
        headers=SUPERVISOR,
        json={"employee_id": target, "reason": "转接测试"},
    )
    assert switched.status_code == 200, switched.text

    listed = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}/handoffs",
        headers=SUPERVISOR,
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] == 1
    handoff = body["items"][0]
    assert handoff["kind"] == "OPERATOR_SWITCH"
    assert handoff["from_employee_id"] == source
    assert handoff["to_employee_id"] == target
    assert handoff["summary"]["operator_reason"] == "转接测试"

    denied = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}/handoffs",
        headers=REQUESTER,
    )
    assert denied.status_code == 403


# --- retry -----------------------------------------------------------------


def test_retry_requeues_a_retryable_turn(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Keep the dispatch out of this test so the response and the row are the
    # retry endpoint's own output, not a worker finishing immediately.
    dispatched: list[UUID] = []
    monkeypatch.setattr(
        "ticket_agent.customer_service.router.process_conversation_turn",
        lambda turn_id, correlation_id: dispatched.append(turn_id),
    )
    conversation_id, turn_id = _small_talk_turn(client)
    _force_turn_status(turn_id, "FAILED_RETRYABLE", attempt_count=2)
    with SessionLocal() as session:
        turn = session.get(ConversationTurn, UUID(turn_id))
        assert turn is not None
        turn.error_code = "TURN_PROCESSING_FAILED"
        turn.error_message = "处理失败：TimeoutError"
        session.commit()
    assert conversation_id

    response = client.post(
        f"/api/v1/customer-service/turns/{turn_id}/retry",
        headers=SUPERVISOR,
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "PENDING"
    assert body["error_code"] is None
    assert body["error_message"] is None
    assert body["attempt_count"] == 2
    assert dispatched == [UUID(turn_id)]

    with SessionLocal() as session:
        turn = session.get(ConversationTurn, UUID(turn_id))
        assert turn is not None
        assert turn.status == "PENDING"
        assert turn.lease_expires_at is not None
    events = _turn_events(turn_id)
    assert events[-1].event_type == "TURN_RETRY_SCHEDULED"
    assert events[-1].payload_json["reason_code"] == "OPERATOR_RETRY"
    assert events[-1].payload_json["previous_status"] == "FAILED_RETRYABLE"
    assert events[-1].actor_type == "AGENT"

    # A queued turn is already owned by the queue.
    repeated = client.post(
        f"/api/v1/customer-service/turns/{turn_id}/retry",
        headers=SUPERVISOR,
    )
    assert repeated.status_code == 409
    assert repeated.json()["code"] == "TURN_IN_PROGRESS"


def test_retry_denies_terminal_in_progress_unknown_and_wrong_roles(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ticket_agent.customer_service.router.process_conversation_turn",
        lambda turn_id, correlation_id: None,
    )
    employee_id = _employee(client, "retry_denied", "重试拒绝客服")
    conversation_id, completed_turn = _small_talk_turn(
        client, employee_id=employee_id
    )
    terminal = client.post(
        f"/api/v1/customer-service/turns/{completed_turn}/retry",
        headers=SUPERVISOR,
    )
    assert terminal.status_code == 409
    assert terminal.json()["code"] == "TURN_ALREADY_TERMINAL"

    running_turn = _queue_pending_turn(
        conversation_id,
        employee_id=employee_id,
        content="还在排队的问题",
    )
    _force_turn_status(running_turn, "RUNNING")
    in_progress = client.post(
        f"/api/v1/customer-service/turns/{running_turn}/retry",
        headers=SUPERVISOR,
    )
    assert in_progress.status_code == 409
    assert in_progress.json()["code"] == "TURN_IN_PROGRESS"

    agent_denied = client.post(
        f"/api/v1/customer-service/turns/{running_turn}/retry",
        headers=AGENT,
    )
    assert agent_denied.status_code == 403

    unknown = client.post(
        f"/api/v1/customer-service/turns/{uuid4()}/retry",
        headers=SUPERVISOR,
    )
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "CONVERSATION_TURN_NOT_FOUND"

    foreign = client.post(
        f"/api/v1/customer-service/turns/{running_turn}/retry",
        headers={**SUPERVISOR, "X-Business-Units": "bu_other"},
    )
    assert foreign.status_code == 403


# --- operations ------------------------------------------------------------


def test_operations_turns_filter_by_status_and_role(
    client: TestClient,
) -> None:
    employee_id = _employee(client, "ops_turns", "运营列表客服")
    conversation_id, completed_turn = _small_talk_turn(
        client, employee_id=employee_id
    )
    stuck_turn = _queue_pending_turn(
        conversation_id,
        employee_id=employee_id,
        content="卡住的问题",
    )
    _force_turn_status(stuck_turn, "RUNNING", lease_offset_seconds=-60)

    all_turns = client.get("/api/v1/operations/turns", headers=SUPERVISOR)
    assert all_turns.status_code == 200, all_turns.text
    assert all_turns.json()["total"] == 2
    assert {item["status"] for item in all_turns.json()["items"]} == {
        "COMPLETED",
        "RUNNING",
    }
    by_id = {item["id"]: item for item in all_turns.json()["items"]}
    assert by_id[stuck_turn]["business_unit_id"] == "bu_demo"
    assert by_id[stuck_turn]["requester_ref"]
    assert by_id[completed_turn]["gate_decision"] == "AUTO_SEND"

    running = client.get(
        "/api/v1/operations/turns",
        headers=SUPERVISOR,
        params={"status": "RUNNING"},
    )
    assert running.status_code == 200, running.text
    assert running.json()["total"] == 1
    assert running.json()["items"][0]["id"] == stuck_turn

    empty = client.get(
        "/api/v1/operations/turns",
        headers=SUPERVISOR,
        params={"status": "FAILED_RETRYABLE"},
    )
    assert empty.status_code == 200
    assert empty.json() == {"items": [], "total": 0}

    denied = client.get("/api/v1/operations/turns", headers=AGENT)
    assert denied.status_code == 403

    # The supervisor is only authorized for bu_demo, so asking for another
    # tenant is rejected before any row is read.
    foreign = client.get(
        "/api/v1/operations/turns",
        headers=SUPERVISOR,
        params={"business_unit_id": "bu_other"},
    )
    assert foreign.status_code == 403


def test_runtime_health_reports_rates_and_stuck_turns(
    client: TestClient,
) -> None:
    employee_id = _employee(client, "runtime_health", "健康度客服")
    _small_talk_turn(client, employee_id=employee_id)
    second_conversation, _ = _small_talk_turn(
        client, employee_id=employee_id
    )
    stuck_turn = _queue_pending_turn(
        second_conversation,
        employee_id=employee_id,
        content="卡住的第二个问题",
    )
    _force_turn_status(stuck_turn, "RUNNING", lease_offset_seconds=-120)

    response = client.get(
        "/api/v1/operations/runtime-health",
        headers=SUPERVISOR,
        params={"window_hours": 24},
    )
    assert response.status_code == 200, response.text
    health = response.json()
    assert health["business_unit_id"] == "bu_demo"
    assert health["window_hours"] == 24
    assert health["turn_count"] == 3
    assert health["completed_count"] == 2
    assert health["auto_send_count"] == 2
    assert health["human_review_count"] == 0
    assert health["blocked_count"] == 0
    assert health["failed_count"] == 0
    assert health["stuck_turn_count"] == 1
    assert health["auto_send_rate"] == pytest.approx(2 / 3, abs=1e-4)
    assert health["unverified_count"] == 0
    assert health["top_gaps"] == []

    denied = client.get(
        "/api/v1/operations/runtime-health",
        headers=AGENT,
    )
    assert denied.status_code == 403

    invalid_window = client.get(
        "/api/v1/operations/runtime-health",
        headers=SUPERVISOR,
        params={"window_hours": 0},
    )
    assert invalid_window.status_code == 422


# --- RT-30: takeover cancels live turns ------------------------------------


def test_takeover_cancels_queued_turn_before_any_answer(
    client: TestClient,
) -> None:
    employee_id = _employee(client, "takeover_cancel", "接管客服")
    conversation_id = _conversation(
        client,
        requester_ref="takeover-cancel-buyer",
        employee_id=employee_id,
    )
    queued_turn = _queue_pending_turn(
        conversation_id,
        employee_id=employee_id,
        content="我的订单 AB-9001 还没发货",
    )
    before = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}",
        headers=AGENT,
    )
    assert before.status_code == 200

    takeover = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/takeover",
        headers=AGENT,
        json={"expected_version": before.json()["version"]},
    )
    assert takeover.status_code == 200, takeover.text

    with SessionLocal() as session:
        turn = session.get(ConversationTurn, UUID(queued_turn))
        assert turn is not None
        assert turn.status == "CANCELLED"
        assert turn.lease_expires_at is None
    events = _turn_events(queued_turn)
    cancelled = next(
        event for event in events if event.event_type == "TURN_CANCELLED"
    )
    assert cancelled.payload_json["reason_code"] == "HUMAN_TAKEOVER"
    assert cancelled.payload_json["handoff_kind"] == "HUMAN_TAKEOVER"
    assert cancelled.actor_type == "AGENT"
    assert cancelled.actor_id == "agent-1"
    # The takeover is also recorded as a handoff on the turn it interrupted.
    handoff_event = next(
        event for event in events if event.event_type == "HANDOFF_CREATED"
    )
    assert handoff_event.payload_json["kind"] == "HUMAN_TAKEOVER"
    assert handoff_event.actor_id == "agent-1"

    # A late dispatch must not resurrect the cancelled turn or write an
    # assistant message the human would talk over.
    process_conversation_turn(UUID(queued_turn), "late-dispatch")
    with SessionLocal() as session:
        turn = session.get(ConversationTurn, UUID(queued_turn))
        assert turn is not None
        assert turn.status == "CANCELLED"
    roles = [message.role for message in _conversation_messages(conversation_id)]
    assert "ASSISTANT" not in roles


def test_complete_turn_refuses_a_cancelled_turn(client: TestClient) -> None:
    employee_id = _employee(client, "takeover_complete", "接管完成客服")
    conversation_id = _conversation(
        client,
        requester_ref="takeover-complete-buyer",
        employee_id=employee_id,
    )
    queued_turn = _queue_pending_turn(
        conversation_id,
        employee_id=employee_id,
        content="订单 AB-9002 的物流呢",
    )
    with SessionLocal() as session:
        conversation = session.get(CustomerConversation, UUID(conversation_id))
        assert conversation is not None
        message = CustomerMessage(
            conversation_id=conversation.id,
            sequence=2,
            role="ASSISTANT",
            content="这是生成到一半的回复",
            created_by="digital_employee.runtime",
        )
        session.add(message)
        session.flush()
        CustomerConversationService(session)._cancel_active_turns(
            conversation.id,
            actor_id="agent-1",
        )
        with pytest.raises(ApiProblem) as raised:
            CustomerConversationService(session).complete_turn(
                turn_id=UUID(queued_turn),
                assistant_message=message,
                response_provider="stub",
                response_model="stub",
                grounding_status="GROUNDED",
                citations=[],
                trace=[],
                tool_calls=[],
                intent=None,
                analysis={},
            )
        assert raised.value.status_code == 409
        assert raised.value.code == "TURN_CANCELLED"
        # The worker's transaction is rolled back: the half-written assistant
        # message does not survive.
        session.rollback()

    roles = [message.role for message in _conversation_messages(conversation_id)]
    assert roles == ["BUYER"]


# --- RT-07: the ticket body is the current question ------------------------


def test_ticket_body_is_the_current_question_only(client: TestClient) -> None:
    employee_id = _employee(client, "ticket_body", "工单正文客服")
    conversation_id = _conversation(
        client,
        requester_ref="ticket-body-buyer",
        employee_id=employee_id,
    )
    # A legacy conversation may already carry messages before its first ticket
    # is created. The ticket created by the next message must not copy them.
    with SessionLocal() as session:
        conversation = session.get(CustomerConversation, UUID(conversation_id))
        assert conversation is not None
        session.add(
            CustomerMessage(
                conversation_id=conversation.id,
                sequence=1,
                role="BUYER",
                content="历史消息：我的订单 AB-1234 怎么还没到",
                created_by="agent-1",
            )
        )
        session.commit()

    accepted = _send(client, conversation_id, "当前问题：能改地址吗？")
    ticket_id = accepted["current_ticket_id"]
    assert ticket_id is not None

    with SessionLocal() as session:
        ticket = session.get(Ticket, UUID(str(ticket_id)))
        assert ticket is not None
        assert ticket.body == "当前问题：能改地址吗？"
        assert "历史消息" not in ticket.body

# --- human takeover / hand-back ------------------------------------------


def _wait_turn(
    client: TestClient,
    conversation_id: str,
    turn_id: str,
    *,
    timeout_seconds: float = 10.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        response = client.get(
            f"/api/v1/customer-service/conversations/{conversation_id}",
            headers=AGENT,
        )
        assert response.status_code == 200, response.text
        view = response.json()
        current = view.get("current_turn") or {}
        if current.get("id") == turn_id and current.get("status") in {
            "COMPLETED",
            "NEEDS_HUMAN",
            "FAILED_RETRYABLE",
            "FAILED_TERMINAL",
            "CANCELLED",
        }:
            return dict(view)
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"turn {turn_id} did not finish: {current.get('status')}"
            )
        time.sleep(0.05)


def _seed_product_knowledge(
    client: TestClient,
    employee_id: str,
    suffix: str,
) -> None:
    """Publish one product fact so a real turn can complete and remember it."""
    space = client.post(
        "/api/v1/knowledge-spaces",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "code": f"replay_space_{suffix}",
            "name": "回放商品知识",
            "description": "记忆读取验收",
            "domain": "ecommerce",
            "channel": "enterprise_service",
            "category": "保温杯",
            "workflow_key": "customer_service_ticket_v1",
            "owner_id": "admin-1",
            "evaluation_required": False,
        },
    )
    assert space.status_code == 201, space.text
    document = client.post(
        "/api/v1/knowledge-documents",
        headers=ADMIN,
        json={
            "space_id": space.json()["id"],
            "business_unit_id": "bu_demo",
            "title": "保温杯参数",
            "doc_type": "FAQ",
            "owner_id": "admin-1",
            "scope": {},
        },
    )
    assert document.status_code == 201, document.text
    version = client.post(
        f"/api/v1/knowledge-documents/{document.json()['id']}/versions",
        headers=ADMIN,
        json={
            "version_label": "1.0",
            "content": (
                "保温杯内胆为 304 不锈钢，容量 500 毫升，"
                "常温环境下可保温 12 小时。"
            ),
        },
    )
    assert version.status_code == 201, version.text
    published = client.post(
        f"/api/v1/knowledge-documents/{document.json()['id']}/versions/"
        f"{version.json()['id']}/publish",
        headers=ADMIN,
        json={"release_note": "replay memory test"},
    )
    assert published.status_code == 200, published.text
    bound = client.put(
        f"/api/v1/digital-employees/{employee_id}/knowledge-bindings",
        headers=ADMIN,
        json={
            "bindings": [
                {
                    "knowledge_space_id": space.json()["id"],
                    "workflow_key": "customer_service_ticket_v1",
                    "scope": {},
                    "enabled": True,
                }
            ]
        },
    )
    assert bound.status_code == 200, bound.text


def test_small_talk_fast_path_reads_memory_and_records_context(
    client: TestClient,
) -> None:
    suffix = uuid4().hex[:8]
    employee_id = _employee(client, f"fast_memory_{suffix}", "记忆客服")
    _seed_product_knowledge(client, employee_id, suffix)
    conversation_id = _conversation(
        client,
        requester_ref=f"fast-memory-buyer-{suffix}",
        employee_id=employee_id,
    )

    first = _send(
        client,
        conversation_id,
        "订单 AB-9001 的保温杯内胆是什么材质？",
    )
    first_turn = str(first["current_turn"]["id"])
    _wait_turn(client, conversation_id, first_turn)

    # The orchestrator turn wrote the order id into memory...
    greeting = _send(client, conversation_id, "你好")
    greeting_turn = str(greeting["current_turn"]["id"])
    view = _wait_turn(client, conversation_id, greeting_turn)
    assert view["current_turn"]["intent"] == "small_talk"

    detail = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}"
        f"/turns/{greeting_turn}",
        headers=AGENT,
    )
    assert detail.status_code == 200, detail.text
    replay = detail.json()
    # ...and the fast path records the context it assembled, including memory.
    assert replay["context"] is not None
    assert replay["context"]["memory"] is not None
    assert replay["context"]["memory"]["fact_count"] >= 1
    assert replay["context"]["history_message_count"] >= 2
    events = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}"
        f"/turns/{greeting_turn}/events",
        headers=AGENT,
    )
    assert events.status_code == 200, events.text
    event_types = [event["event_type"] for event in events.json()["events"]]
    assert "CONTEXT_ASSEMBLED" in event_types

    assistant = [
        message["content"]
        for message in view["messages"]
        if message["role"] == "ASSISTANT"
    ][-1]
    assert "AB-9001" in assistant


def test_human_takeover_owns_the_conversation_until_released(
    client: TestClient,
) -> None:
    suffix = uuid4().hex[:8]
    employee_id = _employee(client, f"human_owner_{suffix}", "人工接管客服")
    _seed_product_knowledge(client, employee_id, suffix)
    conversation_id = _conversation(
        client,
        requester_ref=f"human-owner-buyer-{suffix}",
        employee_id=employee_id,
    )
    first = _send(client, conversation_id, "保温杯能保温多久？")
    _wait_turn(client, conversation_id, str(first["current_turn"]["id"]))
    before = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}",
        headers=AGENT,
    ).json()
    assistant_count = sum(
        message["role"] == "ASSISTANT" for message in before["messages"]
    )
    ticket_id = before["current_ticket_id"]
    assert ticket_id

    takeover = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/takeover",
        headers=AGENT,
        json={"expected_version": before["version"]},
    )
    assert takeover.status_code == 200, takeover.text
    assert takeover.json()["assigned_agent_id"] == "agent-1"

    handoffs = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}/handoffs",
        headers=AGENT,
    )
    assert handoffs.status_code == 200, handoffs.text
    latest = handoffs.json()["items"][0]
    assert latest["kind"] == "HUMAN_TAKEOVER"
    assert latest["to_employee_id"] is None
    assert latest["from_employee_id"] == employee_id
    assert latest["summary"]["taken_over_by"] == "agent-1"

    # The buyer keeps writing, but the digital employee stays silent while a
    # human owns the conversation.
    owned = _send(client, conversation_id, "你好")
    assert owned["current_turn"]["status"] == "NEEDS_HUMAN"
    assert sum(
        message["role"] == "ASSISTANT" for message in owned["messages"]
    ) == assistant_count
    assert (
        client.get(f"/api/v1/tickets/{ticket_id}", headers=AGENT).json()[
            "status"
        ]
        == "WAITING_HUMAN"
    )

    replied = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}"
        "/manual-replies",
        headers=AGENT,
        json={"content": "我来帮你确认保温时长。", "resolve": False},
    )
    assert replied.status_code == 201, replied.text
    still_owned = _send(client, conversation_id, "谢谢")
    assert still_owned["current_turn"]["status"] == "NEEDS_HUMAN"

    resolved = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}"
        "/manual-replies",
        headers=AGENT,
        json={"content": "已确认，可保温 12 小时。", "resolve": True},
    )
    assert resolved.status_code == 201, resolved.text
    assert resolved.json()["assigned_agent_id"] is None

    handoffs = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}/handoffs",
        headers=AGENT,
    )
    assert handoffs.status_code == 200, handoffs.text
    items = handoffs.json()["items"]
    # The list is oldest first, so the hand-back is the last entry.
    returned = items[-1]
    assert returned["kind"] == "HUMAN_RETURN"
    assert returned["from_employee_id"] is None
    assert returned["to_employee_id"] == employee_id
    assert returned["summary"]["last_answer"]["text"] == "已确认，可保温 12 小时。"
    assert returned["summary"]["last_answer"]["by"] == "human"
    assert any(item["kind"] == "HUMAN_TAKEOVER" for item in items)

    # Handed back: the digital employee answers again, and its context labels
    # the human's reply as human, not as its own.
    back = _send(client, conversation_id, "你好")
    back_turn = str(back["current_turn"]["id"])
    back_view = _wait_turn(client, conversation_id, back_turn)
    assert back_view["current_turn"]["status"] == "COMPLETED"
    assert back_view["messages"][-1]["role"] == "ASSISTANT"

    with SessionLocal() as session:
        message = session.scalar(
            select(CustomerMessage)
            .where(CustomerMessage.turn_id == UUID(back_turn))
            .where(CustomerMessage.role == "BUYER")
        )
        assert message is not None
        context = assemble_context(
            session,
            conversation_id=UUID(conversation_id),
            current_message=message,
        )
    assert any(
        line.startswith("客服（人工）：") for line in context.history
    ), context.history
    assert context.handoff is not None
    assert context.handoff.kind == "HUMAN_RETURN"



def test_completed_ticket_reopens_when_the_owner_keeps_talking(
    client: TestClient,
) -> None:
    """A human who takes over a finished conversation must still be able to reply.

    The takeover itself does not reopen a completed ticket, so the buyer's next
    message has to move it back to a state the workbench accepts; otherwise the
    human reply fails with ``CONVERSATION_NOT_AWAITING_HUMAN``.
    """
    suffix = uuid4().hex[:8]
    employee_id = _employee(client, f"reopen_{suffix}", "接管后重开客服")
    _seed_product_knowledge(client, employee_id, suffix)
    conversation_id = _conversation(
        client,
        requester_ref=f"reopen-buyer-{suffix}",
        employee_id=employee_id,
    )
    first = _send(client, conversation_id, "保温杯能保温多久？")
    _wait_turn(client, conversation_id, str(first["current_turn"]["id"]))
    before = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}",
        headers=AGENT,
    ).json()
    ticket_id = before["current_ticket_id"]
    _force_ticket_completed(ticket_id)
    ticket = client.get(f"/api/v1/tickets/{ticket_id}", headers=AGENT).json()
    assert ticket["workflow_state"] == "COMPLETED", ticket

    takeover = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/takeover",
        headers=AGENT,
        json={"expected_version": before["version"]},
    )
    assert takeover.status_code == 200, takeover.text
    # Taking over an idle, finished conversation leaves the ticket closed.
    assert (
        client.get(f"/api/v1/tickets/{ticket_id}", headers=AGENT).json()[
            "workflow_state"
        ]
        == "COMPLETED"
    )

    owned = _send(client, conversation_id, "我还有个问题。")
    assert owned["current_turn"]["status"] == "NEEDS_HUMAN"
    assert owned["current_ticket_id"] == ticket_id
    reopened = client.get(f"/api/v1/tickets/{ticket_id}", headers=AGENT).json()
    assert reopened["workflow_state"] == "NEEDS_HUMAN"
    assert reopened["status"] == "WAITING_HUMAN"
    assert reopened["needs_human"] is True

    replied = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}"
        "/manual-replies",
        headers=AGENT,
        json={"content": "人工回复：可保温 12 小时。", "resolve": True},
    )
    assert replied.status_code == 201, replied.text
    assert replied.json()["assigned_agent_id"] is None
    handoffs = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}/handoffs",
        headers=AGENT,
    ).json()["items"]
    assert [item["kind"] for item in handoffs] == [
        "HUMAN_TAKEOVER",
        "HUMAN_RETURN",
    ]
    assert handoffs[-1]["summary"]["last_answer"]["text"] == "人工回复：可保温 12 小时。"

    # The next buyer message is answered by the digital employee again.
    back = _send(client, conversation_id, "你好")
    back_view = _wait_turn(
        client, conversation_id, str(back["current_turn"]["id"])
    )
    assert back_view["current_turn"]["status"] == "COMPLETED"


# --- deadlock recovery: takeover vs. the worker finishing a turn -----------


class _DeadlockOrigin(Exception):
    sqlstate = "40P01"


def _deadlock_error() -> OperationalError:
    return OperationalError(
        "SELECT conversation_turns ... FOR UPDATE",
        {},
        _DeadlockOrigin("deadlock detected"),
    )


def test_takeover_retries_after_a_deadlock(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee_id = _employee(client, "deadlock_takeover", "死锁接管客服")
    conversation_id = _conversation(
        client,
        requester_ref="deadlock-takeover-buyer",
        employee_id=employee_id,
    )
    queued_turn = _queue_pending_turn(
        conversation_id,
        employee_id=employee_id,
        content="我的订单 AB-9101 还没发货",
    )
    original = CustomerConversationService._takeover_once
    calls: list[int] = []

    def flaky(
        self: CustomerConversationService,
        conversation_id: UUID,
        *,
        expected_version: int,
        agent_id: str,
    ) -> CustomerConversation:
        calls.append(1)
        if len(calls) == 1:
            # The first attempt lost a lock cycle against the worker.
            raise _deadlock_error()
        return original(
            self,
            conversation_id,
            expected_version=expected_version,
            agent_id=agent_id,
        )

    monkeypatch.setattr(CustomerConversationService, "_takeover_once", flaky)
    before = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}",
        headers=AGENT,
    )
    takeover = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/takeover",
        headers=AGENT,
        json={"expected_version": before.json()["version"]},
    )

    assert takeover.status_code == 200, takeover.text
    assert len(calls) == 2
    assert takeover.json()["assigned_agent_id"] == "agent-1"
    with SessionLocal() as session:
        turn = session.get(ConversationTurn, UUID(queued_turn))
        assert turn is not None
        assert turn.status == "CANCELLED"
    handoffs = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}/handoffs",
        headers=AGENT,
    ).json()["items"]
    assert [item["kind"] for item in handoffs] == ["HUMAN_TAKEOVER"]


def test_takeover_does_not_retry_a_stale_version(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee_id = _employee(client, "stale_takeover", "过期接管客服")
    conversation_id = _conversation(
        client,
        requester_ref="stale-takeover-buyer",
        employee_id=employee_id,
    )
    original = CustomerConversationService._takeover_once
    calls: list[int] = []

    def counted(
        self: CustomerConversationService,
        conversation_id: UUID,
        *,
        expected_version: int,
        agent_id: str,
    ) -> CustomerConversation:
        calls.append(1)
        return original(
            self,
            conversation_id,
            expected_version=expected_version,
            agent_id=agent_id,
        )

    monkeypatch.setattr(CustomerConversationService, "_takeover_once", counted)
    current = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}",
        headers=AGENT,
    ).json()
    takeover = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/takeover",
        headers=AGENT,
        json={"expected_version": current["version"] + 1},
    )

    assert takeover.status_code == 409, takeover.text
    assert takeover.json()["code"] == "CONVERSATION_VERSION_CONFLICT"
    assert len(calls) == 1


def test_dispatch_retries_a_turn_whose_transaction_deadlocked(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee_id = _employee(client, "deadlock_dispatch", "死锁重试客服")
    conversation_id = _conversation(
        client,
        requester_ref="deadlock-dispatch-buyer",
        employee_id=employee_id,
    )
    queued_turn = _queue_pending_turn(
        conversation_id,
        employee_id=employee_id,
        content="我的订单 AB-9102 一直没发货，能查一下吗？",
    )
    original = ConversationTurnOrchestrator.process
    calls: list[int] = []

    def flaky(
        self: ConversationTurnOrchestrator,
        turn_id: UUID,
        *,
        correlation_id: str,
    ) -> UUID | None:
        calls.append(1)
        if len(calls) == 1:
            raise _deadlock_error()
        return original(self, turn_id, correlation_id=correlation_id)

    monkeypatch.setattr(ConversationTurnOrchestrator, "process", flaky)
    process_conversation_turn(UUID(queued_turn), "deadlock-retry")

    assert len(calls) == 2
    with SessionLocal() as session:
        turn = session.get(ConversationTurn, UUID(queued_turn))
        assert turn is not None
        assert turn.status in {
            "COMPLETED",
            "NEEDS_HUMAN",
            "FAILED_RETRYABLE",
            "FAILED_TERMINAL",
        }
        assert turn.lease_expires_at is None

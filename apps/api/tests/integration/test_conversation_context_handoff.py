from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from ticket_agent.customer_service.context import assemble_context
from ticket_agent.customer_service.handoffs import create_handoff
from ticket_agent.customer_service.models import (
    ConversationHandoff,
    ConversationMemory,
    ConversationTurn,
    CustomerConversation,
    CustomerMessage,
)
from ticket_agent.customer_service.service import CustomerConversationService
from ticket_agent.customer_service.turns import process_conversation_turn
from ticket_agent.shared.db import SessionLocal
from ticket_agent.shared.settings import get_settings
from ticket_agent.tickets.models import Ticket

ADMIN = {"X-Actor-Id": "admin-1", "X-Actor-Role": "admin"}
AGENT = {"X-Actor-Id": "agent-1", "X-Actor-Role": "agent"}
SUPERVISOR = {"X-Actor-Id": "supervisor-1", "X-Actor-Role": "supervisor"}


def _employee(
    client: TestClient,
    key: str,
    name: str,
    *,
    scenario_type: str = "customer_service_ticket",
    workflow_key: str = "customer_service_ticket_v1",
) -> str:
    response = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json={
            "employee_key": key,
            "name": name,
            "version": "1.0.0",
            "scenario_type": scenario_type,
            "workflow_key": workflow_key,
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
    employee_id: str,
    requester_ref: str,
) -> str:
    response = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "employee_id": employee_id,
            "requester_ref": requester_ref,
        },
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


def test_repeated_client_message_id_is_a_replay(client: TestClient) -> None:
    employee_id = _employee(client, "replay_employee", "重复提交客服")
    conversation_id = _conversation(
        client,
        employee_id=employee_id,
        requester_ref="replay-buyer",
    )

    first = _send(
        client,
        conversation_id,
        "你好",
        client_message_id="client-msg-1",
    )
    second = _send(
        client,
        conversation_id,
        "你好",
        client_message_id="client-msg-1",
    )

    assert first["replayed"] is False
    assert second["replayed"] is True
    assert second["current_turn"]["id"] == first["current_turn"]["id"]
    with SessionLocal() as session:
        turns = list(
            session.scalars(
                select(ConversationTurn).where(
                    ConversationTurn.conversation_id == UUID(conversation_id)
                )
            ).all()
        )
        messages = list(
            session.scalars(
                select(CustomerMessage).where(
                    CustomerMessage.conversation_id == UUID(conversation_id)
                )
            ).all()
        )
    assert len(turns) == 1
    # The replay wrote neither a message nor a turn.
    assert len(messages) == 2


def test_turn_context_snapshot_records_memory_and_labels(
    client: TestClient,
) -> None:
    employee_id = _employee(client, "context_employee", "上下文客服")
    conversation_id = _conversation(
        client,
        employee_id=employee_id,
        requester_ref="context-buyer",
    )
    _send(client, conversation_id, "你好")

    accepted = _send(
        client,
        conversation_id,
        "我的订单 AB-1001 一直没发货，能帮我查一下吗？",
        client_message_id="context-msg-2",
    )
    turn_id = accepted["current_turn"]["id"]
    process_conversation_turn(UUID(turn_id), "context-test")

    with SessionLocal() as session:
        turn = session.get(ConversationTurn, UUID(turn_id))
        assert turn is not None
        context = turn.context_json
        buyer_message = session.get(CustomerMessage, turn.user_message_id)
        memory = session.get(ConversationMemory, UUID(conversation_id))
        assistant_message = (
            session.get(CustomerMessage, turn.assistant_message_id)
            if turn.assistant_message_id is not None
            else None
        )

    # Every message now points at the turn that produced it.
    assert buyer_message is not None and buyer_message.turn_id == UUID(turn_id)
    if assistant_message is not None:
        assert assistant_message.turn_id == UUID(turn_id)
    # The snapshot says what the runtime assembled, whether or not the turn
    # produced an answer (this conversation has no published knowledge, so the
    # turn ends FAILED_TERMINAL after the context was already recorded).
    assert context["schema_version"] == 2
    assert context["history_message_count"] == 2
    assert context["history_sequences"] == [1, 2]
    assert context["memory"]["last_turn_sequence"] == 1
    assert context["memory"]["schema_version"] == 2
    assert context["truncated"] is False
    # Memory was written back in the v2 shape by the answered first turn.
    assert memory is not None
    assert memory.schema_version == 2
    assert memory.summarized_through_sequence == 1
    assert memory.version >= 2


def test_context_assembly_labels_the_employee_who_answered(
    client: TestClient,
) -> None:
    employee_id = _employee(client, "label_employee", "王芳")
    conversation_id = _conversation(
        client,
        employee_id=employee_id,
        requester_ref="label-buyer",
    )
    _send(client, conversation_id, "你好")
    with SessionLocal() as session:
        conversation = session.get(CustomerConversation, UUID(conversation_id))
        assert conversation is not None
        current = CustomerMessage(
            conversation_id=conversation.id,
            sequence=99,
            role="BUYER",
            content="第二个问题",
            created_by="agent-1",
        )
        session.add(current)
        session.flush()
        context = assemble_context(
            session,
            conversation_id=conversation.id,
            current_message=current,
        )
        session.commit()

    assistant_lines = [
        line for line in context.history if line.startswith("客服（")
    ]
    assert assistant_lines, context.history
    assert "王芳" in assistant_lines[0]
    assert context.window_text().endswith("买家：第二个问题")


def test_memory_v1_row_is_upgraded_when_it_is_read(
    client: TestClient,
) -> None:
    conversation_id = uuid4()
    with SessionLocal() as session:
        session.add(
            CustomerConversation(
                id=conversation_id,
                business_unit_id="bu_demo",
                requester_ref="legacy-memory-buyer",
                status="ACTIVE",
            )
        )
        session.commit()
        session.add(
            ConversationMemory(
                conversation_id=conversation_id,
                summary="第 1 轮 用户：订单 OLD-7788 在哪",
                slots_json={"order_id": "OLD-7788"},
                last_turn_sequence=1,
                schema_version=1,
                version=1,
            )
        )
        current = CustomerMessage(
            conversation_id=conversation_id,
            sequence=1,
            role="BUYER",
            content="继续",
            created_by="agent-1",
        )
        session.add(current)
        session.commit()

        context = assemble_context(
            session,
            conversation_id=conversation_id,
            current_message=current,
        )
        session.commit()

        memory = session.get(ConversationMemory, conversation_id)
        assert memory is not None
        assert memory.schema_version == 2
        assert memory.version == 2
        assert memory.slots_json["facts"]["order_id"]["value"] == "OLD-7788"

    assert context.memory is not None
    assert context.memory.upgraded_from_v1 is True
    assert any("OLD-7788" in line for line in context.prompt_lines())


def test_memory_records_a_fact_with_its_source_turn(
    client: TestClient,
) -> None:
    employee_id = _employee(client, "memory_fact_employee", "记忆客服")
    conversation_id = _conversation(
        client,
        employee_id=employee_id,
        requester_ref="memory-fact-buyer",
    )
    with SessionLocal() as session:
        conversation = session.get(CustomerConversation, UUID(conversation_id))
        assert conversation is not None
        message = CustomerMessage(
            conversation_id=conversation.id,
            sequence=1,
            role="BUYER",
            content="",
            created_by="agent-1",
        )
        session.add(message)
        session.flush()
        turn = ConversationTurn(
            conversation_id=conversation.id,
            sequence=1,
            status="COMPLETED",
            user_message_id=message.id,
            employee_id=UUID(employee_id),
        )
        session.add(turn)
        session.flush()
        service = CustomerConversationService(session)
        service._update_memory(
            conversation.id,
            turn.sequence,
            "我的订单 AB-4242 什么时候发货？",
            "已为您登记，稍后回复。",
            turn_id=turn.id,
        )
        session.commit()
        memory = session.get(ConversationMemory, conversation.id)

    assert memory is not None
    assert memory.schema_version == 2
    assert memory.summarized_through_sequence == 1
    fact = memory.slots_json["facts"]["order_id"]
    assert fact["value"] == "AB-4242"
    assert fact["status"] == "confirmed"
    assert fact["source_turn_id"] is not None


def test_second_turn_waits_for_the_first(client: TestClient) -> None:
    employee_id = _employee(client, "serial_employee", "串行客服")
    conversation_id = _conversation(
        client,
        employee_id=employee_id,
        requester_ref="serial-buyer",
    )
    # Queue two turns without dispatching them: both are PENDING with a live
    # lease, exactly as the API leaves them before the worker claims one.
    with SessionLocal() as session:
        conversation = session.get(CustomerConversation, UUID(conversation_id))
        assert conversation is not None
        lease = datetime.now(UTC) + timedelta(
            seconds=get_settings().conversation_turn_lease_seconds
        )
        turn_ids = []
        for sequence, content in ((1, "第一个问题"), (2, "第二个问题")):
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
                client_message_id=f"serial-{sequence}",
                lease_expires_at=lease,
            )
            session.add(turn)
            session.flush()
            message.turn_id = turn.id
            turn_ids.append(turn.id)
        session.commit()

    # Dispatching the later turn first must not run it in parallel with the
    # earlier one that still holds a live lease.
    process_conversation_turn(turn_ids[1], "serial-out-of-order")
    with SessionLocal() as session:
        waiting = session.get(ConversationTurn, turn_ids[1])
        assert waiting is not None
        assert waiting.status == "PENDING"
        assert waiting.attempt_count == 0

    # Running the earlier turn finishes it and drains the queue in order.
    process_conversation_turn(turn_ids[0], "serial-in-order")
    with SessionLocal() as session:
        turns = list(
            session.scalars(
                select(ConversationTurn)
                .where(ConversationTurn.conversation_id == UUID(conversation_id))
                .order_by(ConversationTurn.sequence)
            )
        )
    assert [turn.status for turn in turns] != ["PENDING", "PENDING"]
    assert all(turn.attempt_count >= 1 for turn in turns)


def test_supervisor_can_switch_employee_and_the_handoff_feeds_context(
    client: TestClient,
) -> None:
    source_employee = _employee(client, "handoff_source", "原客服")
    target_employee = _employee(client, "handoff_target", "接手客服")
    conversation_id = _conversation(
        client,
        employee_id=source_employee,
        requester_ref="handoff-buyer",
    )
    _send(client, conversation_id, "你好，我的订单 AB-3003 还没发")

    forbidden = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/employee",
        headers=AGENT,
        json={"employee_id": target_employee},
    )
    assert forbidden.status_code == 403

    unchanged = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/employee",
        headers=SUPERVISOR,
        json={"employee_id": source_employee},
    )
    assert unchanged.status_code == 409
    assert unchanged.json()["code"] == "EMPLOYEE_UNCHANGED"

    missing = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/employee",
        headers=SUPERVISOR,
        json={"employee_id": str(uuid4())},
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "EMPLOYEE_NOT_FOUND"

    hr_employee = _employee(
        client,
        "handoff_hr",
        "HR 入职专员",
        scenario_type="hr_onboarding",
        workflow_key="hr_onboarding_document_collection_v1",
    )
    cross_domain = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/employee",
        headers=SUPERVISOR,
        json={"employee_id": hr_employee},
    )
    assert cross_domain.status_code == 409
    assert cross_domain.json()["code"] == "EMPLOYEE_DOMAIN_MISMATCH"

    switched = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/employee",
        headers=SUPERVISOR,
        json={
            "employee_id": target_employee,
            "reason": "原客服不熟悉订单问题",
        },
    )
    assert switched.status_code == 200, switched.text
    body = switched.json()
    assert body["employee_id"] == target_employee
    handoff = body["latest_handoff"]
    assert handoff["kind"] == "OPERATOR_SWITCH"
    assert handoff["reason_code"] == "MANUAL"
    assert handoff["from_employee_name"] == "原客服"
    assert handoff["to_employee_name"] == "接手客服"
    assert handoff["summary"]["operator_reason"] == "原客服不熟悉订单问题"
    assert handoff["summary"]["last_answer"]["text"]
    handoff_id = handoff["id"]

    with SessionLocal() as session:
        stored = session.get(ConversationHandoff, UUID(handoff_id))
        assert stored is not None
        assert str(stored.to_employee_id) == target_employee

    accepted = _send(
        client,
        conversation_id,
        "那现在能查到物流吗？订单 AB-3003",
        client_message_id="handoff-msg-2",
    )
    turn_id = accepted["current_turn"]["id"]
    process_conversation_turn(UUID(turn_id), "handoff-turn")

    with SessionLocal() as session:
        turn = session.get(ConversationTurn, UUID(turn_id))
        assert turn is not None
        assert turn.context_json["handoff"]["id"] == handoff_id
        assert str(turn.handoff_id) == handoff_id
        assert str(turn.employee_id) == target_employee


def test_second_switch_of_the_same_turn_records_its_own_handoff(
    client: TestClient,
) -> None:
    first_employee = _employee(client, "switch_chain_a", "甲客服")
    second_employee = _employee(client, "switch_chain_b", "乙客服")
    third_employee = _employee(client, "switch_chain_c", "丙客服")
    conversation_id = _conversation(
        client,
        employee_id=first_employee,
        requester_ref="switch-chain-buyer",
    )
    _send(client, conversation_id, "你好")

    for target in (second_employee, third_employee):
        response = client.post(
            f"/api/v1/customer-service/conversations/{conversation_id}/employee",
            headers=SUPERVISOR,
            json={"employee_id": target, "reason": "转给更合适的员工"},
        )
        assert response.status_code == 200, response.text

    with SessionLocal() as session:
        handoffs = list(
            session.scalars(
                select(ConversationHandoff)
                .where(ConversationHandoff.conversation_id == UUID(conversation_id))
                .order_by(ConversationHandoff.created_at)
            )
        )
        assert len(handoffs) == 2
        assert str(handoffs[0].from_employee_id) == first_employee
        assert str(handoffs[0].to_employee_id) == second_employee
        assert str(handoffs[1].from_employee_id) == second_employee
        assert str(handoffs[1].to_employee_id) == third_employee
        conversation = session.get(CustomerConversation, UUID(conversation_id))
        assert conversation is not None
        assert str(conversation.employee_id) == third_employee


def test_handoff_is_idempotent_per_source_turn(client: TestClient) -> None:
    employee_id = _employee(client, "handoff_idempotent", "幂等客服")
    conversation_id = _conversation(
        client,
        employee_id=employee_id,
        requester_ref="handoff-idempotent-buyer",
    )
    _send(client, conversation_id, "你好")

    with SessionLocal() as session:
        conversation = session.get(CustomerConversation, UUID(conversation_id))
        assert conversation is not None
        from_turn = session.scalar(
            select(ConversationTurn).where(
                ConversationTurn.conversation_id == conversation.id
            )
        )
        assert from_turn is not None
        first = create_handoff(
            session,
            conversation=conversation,
            from_turn=from_turn,
            to_employee=None,
            kind="HUMAN_TAKEOVER",
            reason_code="ESCALATION",
            actor_id="agent-1",
        )
        second = create_handoff(
            session,
            conversation=conversation,
            from_turn=from_turn,
            to_employee=None,
            kind="HUMAN_TAKEOVER",
            reason_code="ESCALATION",
            actor_id="agent-1",
        )
        session.commit()
        assert first.id == second.id
        assert (
            len(
                list(
                    session.scalars(
                        select(ConversationHandoff).where(
                            ConversationHandoff.conversation_id
                            == conversation.id
                        )
                    )
                )
            )
            == 1
        )


def test_first_message_joins_the_ticket_created_at_the_same_instant(
    client: TestClient,
) -> None:
    """Two first messages must not turn into one 409 and one ticket.

    ``TicketService.create`` commits before the caller records
    ``current_ticket_id``, so a second message can reach the creation branch
    while the ticket already exists. It has to join that ticket instead of
    failing on the conversation's initial idempotency key.
    """
    employee_id = _employee(client, "race_employee", "抢跑客服")
    conversation_id = _conversation(
        client,
        employee_id=employee_id,
        requester_ref="race-buyer",
    )
    first = _send(client, conversation_id, "订单 AB-2001 什么时候发货？")
    ticket_id = first["current_ticket_id"]
    assert ticket_id is not None

    # Rewind to the exact window the racing request sees: the initial ticket
    # is committed but the conversation does not point at it yet.
    with SessionLocal() as session:
        conversation = session.get(CustomerConversation, UUID(conversation_id))
        assert conversation is not None
        conversation.current_ticket_id = None
        session.commit()

    second = _send(
        client,
        conversation_id,
        "顺便问一下，能开发票吗？",
        client_message_id="race-msg-2",
    )
    assert second["current_ticket_id"] == ticket_id
    assert second["current_turn"]["id"] != first["current_turn"]["id"]

    # Every message names the turn it belongs to, so a reader can follow the
    # conversation without opening the database.
    view = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}",
        headers=AGENT,
    )
    assert view.status_code == 200
    buyer_turns = {
        message["content"]: message["turn_id"]
        for message in view.json()["messages"]
        if message["role"] == "BUYER"
    }
    assert buyer_turns["订单 AB-2001 什么时候发货？"] == first["current_turn"]["id"]
    assert buyer_turns["顺便问一下，能开发票吗？"] == second["current_turn"]["id"]

    with SessionLocal() as session:
        initial_tickets = list(
            session.scalars(
                select(Ticket).where(
                    Ticket.source_ticket_id == f"CONV-{conversation_id}-initial"
                )
            )
        )
    assert len(initial_tickets) == 1
    assert str(initial_tickets[0].id) == ticket_id


def test_queued_turn_does_not_see_a_message_sent_after_it(
    client: TestClient,
) -> None:
    """Turn order is causal: the later buyer message stays out of turn one."""
    employee_id = _employee(client, "causal_employee", "顺序客服")
    conversation_id = _conversation(
        client,
        employee_id=employee_id,
        requester_ref="causal-buyer",
    )
    opened = _send(client, conversation_id, "订单 AB-2002 一直没发货")
    ticket_id = UUID(opened["current_ticket_id"])

    # Queue two more turns the way the API leaves them before a worker claims
    # one: the buyer has already sent both when the first of them runs.
    with SessionLocal() as session:
        conversation = session.get(CustomerConversation, UUID(conversation_id))
        assert conversation is not None
        lease = datetime.now(UTC) + timedelta(
            seconds=get_settings().conversation_turn_lease_seconds
        )
        last_sequence = (
            session.scalar(
                select(func.max(CustomerMessage.sequence)).where(
                    CustomerMessage.conversation_id == conversation.id
                )
            )
            or 0
        )
        turn_ids = []
        sequences = []
        for content in ("顺便确认一下发票", "还有别的颜色吗？"):
            sequence = last_sequence + 1
            message = CustomerMessage(
                conversation_id=conversation.id,
                sequence=sequence,
                role="BUYER",
                content=content,
                ticket_id=ticket_id,
                created_by="agent-1",
            )
            session.add(message)
            session.flush()
            turn = ConversationTurn(
                conversation_id=conversation.id,
                ticket_id=ticket_id,
                sequence=sequence,
                status="PENDING",
                user_message_id=message.id,
                employee_id=UUID(employee_id),
                client_message_id=f"causal-{sequence}",
                lease_expires_at=lease,
            )
            session.add(turn)
            session.flush()
            message.turn_id = turn.id
            turn_ids.append(turn.id)
            sequences.append(sequence)
            last_sequence = sequence
        session.commit()

    process_conversation_turn(turn_ids[0], "causal-test")

    with SessionLocal() as session:
        first_turn = session.get(ConversationTurn, turn_ids[0])
        second_turn = session.get(ConversationTurn, turn_ids[1])
        assert first_turn is not None
        assert second_turn is not None
        first_context = first_turn.context_json
        second_context = second_turn.context_json

    # The second queued message already existed while the first queued turn
    # ran, but it was sent after that turn's own message, so it must stay out.
    assert first_context is not None
    assert first_context["history_sequences"]
    assert all(sequence < sequences[0] for sequence in first_context["history_sequences"])
    # The finished turn drains the queue, so the second one ran too, and it may
    # only see what came before its own message.
    assert second_context is not None
    assert all(
        sequence < sequences[1] for sequence in second_context["history_sequences"]
    )

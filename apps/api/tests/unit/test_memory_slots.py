from uuid import uuid4

from ticket_agent.customer_service.context import (
    MAX_COMMITMENTS,
    MAX_OPEN_ACTIONS,
    DerivedSlots,
    MemorySnapshot,
    derive_memory_slots,
    load_memory,
    record_memory_turn,
)
from ticket_agent.customer_service.models import CustomerConversation
from ticket_agent.customer_service.service import CustomerConversationService
from ticket_agent.shared.db import system_session

TURN_ID = "turn-0001"
UPDATED_AT = "2026-11-09T10:00:00+00:00"


def _snapshot(
    *,
    open_actions: list[dict[str, object]] | None = None,
    commitments: list[dict[str, object]] | None = None,
    pending_questions: list[str] | None = None,
) -> MemorySnapshot:
    return MemorySnapshot(
        schema_version=2,
        summary="",
        facts={},
        open_actions=open_actions or [],
        commitments=commitments or [],
        pending_questions=pending_questions or [],
        version=1,
        last_turn_sequence=1,
        upgraded_from_v1=False,
    )


def _derive(
    assistant_content: str,
    *,
    previous: MemorySnapshot | None = None,
    ticket_status: str | None = None,
    turn_sequence: int = 1,
) -> DerivedSlots:
    return derive_memory_slots(
        previous=previous,
        assistant_content=assistant_content,
        turn_sequence=turn_sequence,
        source_turn_id=TURN_ID,
        updated_at=UPDATED_AT,
        ticket_status=ticket_status,
    )


def test_answer_fills_commitments_actions_and_questions() -> None:
    slots = _derive(
        "已为您登记，预计 1-3 个工作日处理。"
        "已转人工跟进。请问您的订单号是多少？"
    )

    assert [item["text"] for item in slots.commitments] == [
        "已为您登记，预计 1-3 个工作日处理",
        "已转人工跟进",
    ]
    assert [item["summary"] for item in slots.open_actions] == ["已转人工跟进"]
    assert slots.pending_questions == ["请问您的订单号是多少"]
    assert all(item["status"] == "open" for item in slots.commitments)
    assert all(item["source_turn_id"] == TURN_ID for item in slots.commitments)
    assert all(
        item["source_turn_id"] == TURN_ID for item in slots.open_actions
    )


def test_new_answer_replaces_previous_pending_questions() -> None:
    previous = _snapshot(pending_questions=["请问您的订单号是多少"])

    slots = _derive("已为您记录，稍后反馈。", previous=previous)

    assert slots.pending_questions == []
    assert len(slots.commitments) == 1


def test_resolved_ticket_closes_actions_but_keeps_commitments() -> None:
    previous = _snapshot(
        open_actions=[
            {
                "summary": "已转人工跟进",
                "status": "open",
                "owner": "employee",
            }
        ],
        commitments=[{"text": "已为您登记", "status": "open"}],
        pending_questions=["还需要其他帮助吗"],
    )

    slots = _derive(
        "问题已解决。",
        previous=previous,
        ticket_status="RESOLVED",
    )

    assert slots.open_actions == []
    assert [item["text"] for item in slots.commitments] == ["已为您登记"]
    assert slots.pending_questions == []


def test_commitments_are_deduplicated_and_capped() -> None:
    previous = _snapshot(
        commitments=[
            {"text": f"已为您安排 {index}", "status": "open"}
            for index in range(MAX_COMMITMENTS)
        ]
    )

    slots = _derive(
        "已为您安排 4。已为您安排 5。已为您安排 5。",
        previous=previous,
        turn_sequence=2,
    )

    texts = [item["text"] for item in slots.commitments]
    assert texts == [
        "已为您安排 1",
        "已为您安排 2",
        "已为您安排 3",
        "已为您安排 4",
        "已为您安排 5",
    ]
    assert len(texts) == MAX_COMMITMENTS


def test_open_actions_are_capped_and_keep_newest() -> None:
    previous = _snapshot(
        open_actions=[
            {"summary": f"处理中事项 {index}", "status": "open"}
            for index in range(MAX_OPEN_ACTIONS)
        ]
    )

    slots = _derive("正在处理事项 5。", previous=previous, turn_sequence=2)

    summaries = [item["summary"] for item in slots.open_actions]
    assert summaries[-1] == "正在处理事项 5"
    assert len(summaries) == MAX_OPEN_ACTIONS
    assert summaries[0] == "处理中事项 1"


def test_record_memory_turn_replaces_slots() -> None:
    conversation_id = uuid4()
    with system_session() as session:
        session.add(
            CustomerConversation(
                id=conversation_id,
                business_unit_id="bu_demo",
                requester_ref="memory-slot-buyer",
                status="ACTIVE",
            )
        )
        session.flush()
        record_memory_turn(
            session,
            conversation_id=conversation_id,
            turn_sequence=1,
            summary="第 1 轮",
            facts={},
            open_actions=[{"summary": "已转人工跟进", "status": "open"}],
            commitments=[{"text": "已为您登记", "status": "open"}],
            pending_questions=["请问订单号是多少"],
        )
        session.commit()
        snapshot = load_memory(session, conversation_id)

    assert snapshot is not None
    assert snapshot.open_actions == [
        {"summary": "已转人工跟进", "status": "open"}
    ]
    assert snapshot.commitments == [{"text": "已为您登记", "status": "open"}]
    assert snapshot.pending_questions == ["请问订单号是多少"]


def test_update_memory_writes_slots_from_the_answer() -> None:
    conversation_id = uuid4()
    with system_session() as session:
        session.add(
            CustomerConversation(
                id=conversation_id,
                business_unit_id="bu_demo",
                requester_ref="memory-writer-buyer",
                status="ACTIVE",
            )
        )
        session.flush()
        service = CustomerConversationService(session)
        service._update_memory(
            conversation_id,
            1,
            "订单 AB-1001 一直没发货",
            "已为您转人工跟进，预计 24 小时内回复。",
            ticket_status=None,
        )
        session.commit()
        snapshot = load_memory(session, conversation_id)

    assert snapshot is not None
    assert [item["summary"] for item in snapshot.open_actions] == [
        "已为您转人工跟进，预计 24 小时内回复"
    ]
    assert [item["text"] for item in snapshot.commitments] == [
        "已为您转人工跟进，预计 24 小时内回复"
    ]
    assert snapshot.facts["order_id"]["value"] == "AB-1001"

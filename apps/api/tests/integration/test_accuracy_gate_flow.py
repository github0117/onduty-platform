from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select

from ticket_agent.customer_service.models import (
    ConversationTurn,
    ConversationTurnEvent,
)
from ticket_agent.customer_service.suggestions import (
    CustomerReplySuggestionService,
)
from ticket_agent.knowledge.gap_events import record_knowledge_gap
from ticket_agent.knowledge.models import (
    KnowledgeGapOccurrence,
    KnowledgeRepairTask,
)
from ticket_agent.knowledge.repair_service import KnowledgeRepairService
from ticket_agent.outbox.service import dispatch_pending_events
from ticket_agent.shared.db import SessionLocal
from ticket_agent.tickets.drafts import DraftResult

ADMIN = {"X-Actor-Id": "admin-1", "X-Actor-Role": "admin"}
AGENT = {"X-Actor-Id": "agent-1", "X-Actor-Role": "agent"}


class _StubGraph:
    def __init__(self, draft: DraftResult) -> None:
        self.draft = draft

    def invoke(self, _state: dict[str, object]) -> dict[str, object]:
        return {
            "draft": self.draft,
            "skill": "stub-skill",
            "skill_definition": None,
            "skill_definition_version": None,
            "trace": ["stub"],
            "mcp_tool_calls": [],
        }


def _employee(client: TestClient, key: str) -> str:
    response = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json={
            "employee_key": key,
            "name": "门禁服务客服",
            "version": "1.0.0",
            "scenario_type": "customer_service_ticket",
            "workflow_key": "customer_service_ticket_v1",
            "business_unit_id": "bu_demo",
            "service_identity": f"digital_employee.{key}",
            "handoff_queue": "MANUAL_TRIAGE",
            "tool_allowlist": [
                "ticket.read",
                "knowledge.search",
                "draft.create",
            ],
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _conversation(client: TestClient, employee_id: str) -> str:
    response = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "employee_id": employee_id,
            "requester_ref": "gate-buyer",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _run_turn(
    client: TestClient,
    monkeypatch,
    *,
    draft: DraftResult,
    key: str,
) -> tuple[dict[str, object], dict[str, object]]:
    employee_id = _employee(client, key)
    conversation_id = _conversation(client, employee_id)
    monkeypatch.setattr(
        CustomerReplySuggestionService,
        "_build_graph",
        lambda self: _StubGraph(draft),
    )
    accepted = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/messages",
        headers=AGENT,
        json={"content": "办公室门禁失灵了怎么处理？"},
    )
    assert accepted.status_code == 202, accepted.text
    dispatch_pending_events()
    detail = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}",
        headers=AGENT,
    )
    assert detail.status_code == 200, detail.text
    return detail.json()["current_turn"], detail.json()


def _claim(*, cited: bool, claim_type: str = "policy") -> dict[str, object]:
    return {
        "text": "门禁维修需由设施团队处理。",
        "claim_type": claim_type,
        "cited_chunk_ids": ["chunk-1"] if cited else [],
        "verification_verdict": "supported",
        "verification_confidence": 0.9,
        "verification_reason": "test",
        "verification_provider": "test",
    }


def test_policy_claim_without_citation_is_persisted_and_blocks_completion(
    client: TestClient,
    monkeypatch,
) -> None:
    draft = DraftResult(
        text="门禁维修需由设施团队处理。",
        citations=[],
        claims=[_claim(cited=False)],
        provider="stub",
        model="stub-v1",
        fallback_used=False,
        grounding_status="GROUNDED",
    )
    turn, _ = _run_turn(client, monkeypatch, draft=draft, key="gate_block")

    assert turn["status"] == "COMPLETED", (
        turn.get("error_code"),
        turn.get("error_message"),
    )
    gate = turn["gate"]
    assert gate is not None
    assert gate["decision"] == "HUMAN_REVIEW"
    assert gate["reasons"] == ["POLICY_CLAIM_WITHOUT_CITATION"]
    assert gate["checks"]["uncited_policy_claim_count"] == 1

    with SessionLocal() as session:
        row = session.get(ConversationTurn, UUID(str(turn["id"])))
        assert row is not None
        assert row.gate_json is not None
        assert row.gate_json["decision"] == "HUMAN_REVIEW"
        events = list(
            session.scalars(
                select(ConversationTurnEvent).where(
                    ConversationTurnEvent.turn_id == row.id,
                    ConversationTurnEvent.event_type == "GATE_EVALUATED",
                )
            ).all()
        )
        assert len(events) == 1
        assert events[0].payload_json["decision"] == "HUMAN_REVIEW"
        assert events[0].payload_json["reasons"] == [
            "POLICY_CLAIM_WITHOUT_CITATION"
        ]

    ticket = client.get(
        f"/api/v1/tickets/{turn['ticket_id']}",
        headers=AGENT,
    )
    assert ticket.status_code == 200, ticket.text
    assert ticket.json()["workflow_state"] != "COMPLETED"


def test_gate_cleared_grounded_turn_still_completes_ticket(
    client: TestClient,
    monkeypatch,
) -> None:
    draft = DraftResult(
        text="门禁维修需由设施团队处理。",
        citations=[
            {
                "chunk_id": "chunk-1",
                "document_id": "document-1",
                "title": "门禁维修说明",
                "version": "1.0",
            }
        ],
        claims=[_claim(cited=True)],
        provider="stub",
        model="stub-v1",
        fallback_used=False,
        grounding_status="GROUNDED",
    )
    turn, _ = _run_turn(client, monkeypatch, draft=draft, key="gate_allow")

    assert turn["status"] == "COMPLETED"
    gate = turn["gate"]
    assert gate is not None
    assert gate["decision"] == "AUTO_SEND"
    assert gate["reasons"] == []

    ticket = client.get(
        f"/api/v1/tickets/{turn['ticket_id']}",
        headers=AGENT,
    )
    assert ticket.status_code == 200, ticket.text
    assert ticket.json()["workflow_state"] == "COMPLETED"


def test_repeated_no_knowledge_question_opens_one_repair_task(
    client: TestClient,
) -> None:
    query = "门禁卡补办需要几天？"
    with SessionLocal() as session:
        first = record_knowledge_gap(
            session,
            business_unit_id="bu_demo",
            query=query,
        )
        session.commit()
        assert first is not None
        assert first.repair_task_id is None

        second = record_knowledge_gap(
            session,
            business_unit_id="bu_demo",
            query=f"  {query}  ",
        )
        session.commit()
        assert second is not None
        assert second.repair_task_id is None

        third = record_knowledge_gap(
            session,
            business_unit_id="bu_demo",
            query=query,
        )
        session.commit()
        assert third is not None
        assert third.repair_task_id is not None
        task = session.get(KnowledgeRepairTask, third.repair_task_id)
        assert task is not None
        assert task.status == "OPEN"
        assert task.business_unit_id == "bu_demo"
        assert task.query == query
        assert task.title.startswith("运行时知识缺口：")

        linked = list(
            session.scalars(
                select(KnowledgeGapOccurrence).where(
                    KnowledgeGapOccurrence.repair_task_id == task.id
                )
            ).all()
        )
        assert len(linked) == 3

        # A fourth occurrence joins the existing task instead of opening a
        # second one.
        fourth = record_knowledge_gap(
            session,
            business_unit_id="bu_demo",
            query=query,
        )
        session.commit()
        assert fourth is not None
        assert fourth.repair_task_id == task.id
        task_count = len(
            session.scalars(select(KnowledgeRepairTask)).all()
        )
        assert task_count == 1

        listed = KnowledgeRepairService(session).list(
            business_unit_id="bu_demo"
        )
        listed_task = next(
            item for item in listed.items if item.id == task.id
        )
        assert listed_task.occurrence_count == 4

        # A closed task is reopened when the same gap recurs.
        task.status = "CLOSED"
        task.resolved_at = datetime.now(UTC)
        session.commit()
        reopened = record_knowledge_gap(
            session,
            business_unit_id="bu_demo",
            query=query,
        )
        session.commit()
        assert reopened is not None
        session.refresh(task)
        assert task.status == "OPEN"
        assert task.resolved_at is None


def test_knowledge_gaps_are_scoped_per_business_unit(
    client: TestClient,
) -> None:
    with SessionLocal() as session:
        for _ in range(2):
            record_knowledge_gap(
                session,
                business_unit_id="bu_demo",
                query="跨租户问题",
            )
        other = record_knowledge_gap(
            session,
            business_unit_id="bu_other",
            query="跨租户问题",
        )
        session.commit()
        assert other is not None
        assert other.repair_task_id is None
        tasks = list(session.scalars(select(KnowledgeRepairTask)).all())
        assert tasks == []

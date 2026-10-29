from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from ticket_agent.customer_service.models import (
    ConversationTurn,
    ConversationTurnEvent,
)
from ticket_agent.customer_service.suggestions import (
    GENERAL_SKILL_CODE,
    CustomerReplySuggestionService,
)
from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.outbox.service import dispatch_pending_events
from ticket_agent.shared.db import SessionLocal

ADMIN = {"X-Actor-Id": "admin-1", "X-Actor-Role": "admin"}
AGENT = {"X-Actor-Id": "agent-1", "X-Actor-Role": "agent"}


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
            "tool_allowlist": [
                "ticket.read",
                "knowledge.search",
                "draft.create",
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _seed_aftersales_knowledge(
    client: TestClient,
    employee_id: str,
) -> str:
    space = client.post(
        "/api/v1/knowledge-spaces",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "code": f"contract_space_{uuid4().hex[:8]}",
            "name": "退款契约知识",
            "description": "Skill 完成度验收",
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
            "title": "退款与退货政策",
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
                "退款：买家发起退款需先确认订单号和商品；"
                "售后政策为签收后 7 天内可申请退款或退货，"
                "退款金额和资格以人工审核结果为准，客服不得自行承诺。"
            ),
        },
    )
    assert version.status_code == 201, version.text
    published = client.post(
        (
            f"/api/v1/knowledge-documents/{document.json()['id']}/versions/"
            f"{version.json()['id']}/publish"
        ),
        headers=ADMIN,
        json={"release_note": "skill contract test"},
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
    return space.json()["id"]


def test_skill_definition_roundtrip_and_version_conflict(
    client: TestClient,
) -> None:
    definition = {
        "schema_version": 1,
        "steps": [
            {
                "id": "identify_order",
                "name": "确认订单",
                "required": True,
                "evidence": ["slot:order_id"],
                "completion": "order_id != null",
            }
        ],
        "completion_criteria": ["all_required_steps_done"],
    }
    created = client.post(
        "/api/v1/skills",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "code": "refund-contract",
            "name": "退款契约",
            "instructions": "核对订单后再处理退款。",
            "triggers": ["退款"],
            "definition": definition,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["definition"]["steps"][0]["id"] == "identify_order"
    assert body["definition_version"] == 1
    assert body["version"] == 1
    skill_id = body["id"]

    updated = client.patch(
        f"/api/v1/skills/{skill_id}",
        headers=ADMIN,
        json={
            "expected_version": 1,
            "definition": {
                **definition,
                "steps": [
                    *definition["steps"],
                    {
                        "id": "check_policy",
                        "name": "核对政策",
                        "required": True,
                        "evidence": ["knowledge:aftersales"],
                        "completion": "citation_count > 0",
                    },
                ],
            },
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    assert updated.json()["definition_version"] == 2
    assert len(updated.json()["definition"]["steps"]) == 2

    conflict = client.patch(
        f"/api/v1/skills/{skill_id}",
        headers=ADMIN,
        json={"expected_version": 1, "name": "过期编辑"},
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == "SKILL_VERSION_CONFLICT"


def test_invalid_skill_definition_is_rejected(
    client: TestClient,
) -> None:
    invalid = client.post(
        "/api/v1/skills",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "code": "broken-contract",
            "name": "坏契约",
            "instructions": "任意",
            "definition": {
                "schema_version": 1,
                "steps": [
                    {
                        "id": "Bad Step",
                        "name": "非法 ID",
                    }
                ],
            },
        },
    )
    assert invalid.status_code == 422, invalid.text


def test_no_trigger_match_uses_general_not_first_binding(
    client: TestClient,
) -> None:
    employee_id = _employee(client, "contract_selector", "契约选择客服")
    skills = client.get(
        "/api/v1/skills?business_unit_id=bu_demo",
        headers=ADMIN,
    ).json()
    by_code = {skill["code"]: skill for skill in skills}
    bound = client.put(
        f"/api/v1/digital-employees/{employee_id}/skills",
        headers=ADMIN,
        json={
            "bindings": [
                {
                    "skill_id": by_code["ecommerce-aftersales"]["id"],
                    "enabled": True,
                    "priority": 10,
                },
                {
                    "skill_id": by_code["logistics-inquiry"]["id"],
                    "enabled": True,
                    "priority": 20,
                },
            ]
        },
    )
    assert bound.status_code == 200, bound.text

    with SessionLocal() as session:
        employee = session.get(DigitalEmployee, UUID(employee_id))
        assert employee is not None
        service = CustomerReplySuggestionService(session)
        unmatched = service._route_skill(
            {
                "query": "今天天气怎么样",
                "ticket": SimpleNamespace(category_primary=None),
                "employee": employee,
                "trace": [],
            }
        )
        matched = service._route_skill(
            {
                "query": "我要退款",
                "ticket": SimpleNamespace(category_primary=None),
                "employee": employee,
                "trace": [],
            }
        )

    assert unmatched["skill"] == GENERAL_SKILL_CODE
    assert unmatched["skill_definition"] is None
    assert matched["skill"] == "ecommerce-aftersales"
    assert matched["skill_definition"] is not None


def test_missing_required_step_blocks_completed_turn(
    client: TestClient,
) -> None:
    employee_id = _employee(client, "contract_turn", "契约回合客服")
    _seed_aftersales_knowledge(client, employee_id)
    conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "employee_id": employee_id,
            "requester_ref": "contract-buyer",
        },
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]

    accepted = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/messages",
        headers=AGENT,
        json={"content": "我要申请退款"},
    )
    assert accepted.status_code == 202, accepted.text
    dispatch_pending_events()

    detail = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}",
        headers=AGENT,
    )
    assert detail.status_code == 200, detail.text
    turn = detail.json()["current_turn"]
    assert turn["status"] == "NEEDS_HUMAN", detail.text

    with SessionLocal() as session:
        row = session.get(ConversationTurn, UUID(turn["id"]))
        assert row is not None
        assert row.skill_code == "ecommerce-aftersales"
        assert row.completion_json is not None
        assert row.completion_json["complete"] is False
        assert "identify_order" in row.completion_json["incomplete_required"]
        snapshot = row.skill_snapshot_json
        assert snapshot is not None
        assert snapshot["definition"]["steps"]
        definition_version = snapshot["definition_version"]
        events = list(
            session.scalars(
                select(ConversationTurnEvent)
                .where(ConversationTurnEvent.turn_id == row.id)
                .order_by(ConversationTurnEvent.sequence)
            ).all()
        )
    event_types = [event.event_type for event in events]
    assert "SKILL_SELECTED" in event_types
    assert "COMPLETION_EVALUATED" in event_types

    ticket = client.get(
        f"/api/v1/tickets/{turn['ticket_id']}",
        headers=AGENT,
    )
    assert ticket.status_code == 200, ticket.text
    assert ticket.json()["workflow_state"] != "COMPLETED"

    # Editing the Skill afterwards must not rewrite the finished turn.
    skills = client.get(
        "/api/v1/skills?business_unit_id=bu_demo",
        headers=ADMIN,
    ).json()
    aftersales = next(
        skill for skill in skills if skill["code"] == "ecommerce-aftersales"
    )
    edited = client.patch(
        f"/api/v1/skills/{aftersales['id']}",
        headers=ADMIN,
        json={
            "expected_version": aftersales["version"],
            "definition": {
                "schema_version": 1,
                "steps": [
                    {
                        "id": "simplified",
                        "name": "简化步骤",
                        "required": False,
                    }
                ],
                "completion_criteria": ["all_required_steps_done"],
            },
        },
    )
    assert edited.status_code == 200, edited.text
    with SessionLocal() as session:
        row = session.get(ConversationTurn, UUID(turn["id"]))
        assert row is not None
        assert row.skill_snapshot_json is not None
        assert row.skill_snapshot_json["definition_version"] == definition_version
        assert (
            row.skill_snapshot_json["definition"]["steps"][0]["id"]
            == "identify_order"
        )

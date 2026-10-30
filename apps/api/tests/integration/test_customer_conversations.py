import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select

from ticket_agent.customer_service.models import (
    AgentPresence,
    ConversationMemory,
    ConversationTurn,
    CustomerConversation,
    CustomerMessage,
)
from ticket_agent.customer_service.suggestions import (
    CustomerReplySuggestionService,
)
from ticket_agent.digital_employees.models import DigitalEmployeeRouteDecision
from ticket_agent.shared.db import SessionLocal
from ticket_agent.tickets.drafts import DraftResult
from ticket_agent.tickets.models import Ticket

ADMIN = {"X-Actor-Id": "admin-1", "X-Actor-Role": "admin"}
AGENT = {"X-Actor-Id": "agent-1", "X-Actor-Role": "agent"}


def test_small_talk_uses_deterministic_turn_without_ticket(
    client: TestClient,
) -> None:
    conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "requester_ref": "small-talk-buyer",
            "channel": "enterprise_service",
        },
    )
    assert conversation.status_code == 201
    conversation_id = conversation.json()["id"]

    accepted = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/messages",
        headers=AGENT,
        json={"content": "你好"},
    )

    assert accepted.status_code == 202
    payload = accepted.json()
    assert payload["current_ticket_id"] is None
    assert [item["role"] for item in payload["messages"]] == [
        "BUYER",
        "ASSISTANT",
    ]
    assert payload["current_turn"]["status"] == "COMPLETED"
    assert payload["current_turn"]["intent"] == "small_talk"
    assert payload["current_turn"]["response_model"] == "small-talk-v1"
    with SessionLocal() as session:
        turn = session.scalar(
            select(ConversationTurn).where(
                ConversationTurn.conversation_id == UUID(conversation_id)
            )
        )
        memory = session.get(ConversationMemory, UUID(conversation_id))
        assert turn is not None
        assert turn.ticket_id is None
        assert memory is not None
        assert memory.last_turn_sequence == 1


def test_conversation_reuses_one_ticket_across_normal_turns(
    client: TestClient,
) -> None:
    employee = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json={
            "employee_key": "single_ticket_employee",
            "name": "单工单客服",
            "version": "1.0.0",
            "scenario_type": "customer_service_ticket",
            "workflow_key": "customer_service_ticket_v1",
            "business_unit_id": "bu_demo",
            "service_identity": "digital_employee.single_ticket",
            "handoff_queue": "MANUAL_TRIAGE",
            "tool_allowlist": [
                "ticket.read",
                "knowledge.search",
                "draft.create",
            ],
        },
    )
    assert employee.status_code == 201
    conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "employee_id": employee.json()["id"],
            "requester_ref": "single-ticket-buyer",
        },
    )
    conversation_id = conversation.json()["id"]

    first = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/messages",
        headers=AGENT,
        json={"content": "第一个问题"},
    )
    second = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/messages",
        headers=AGENT,
        json={"content": "第二个问题"},
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["current_ticket_id"] == second.json()["current_ticket_id"]
    with SessionLocal() as session:
        turns = list(
            session.scalars(
                select(ConversationTurn)
                .where(
                    ConversationTurn.conversation_id
                    == UUID(conversation_id)
                )
                .order_by(ConversationTurn.sequence)
            ).all()
        )
        tickets = list(
            session.scalars(
                select(Ticket).where(
                    Ticket.id == UUID(first.json()["current_ticket_id"])
                )
            ).all()
        )
        assert [turn.sequence for turn in turns] == [1, 2]
        assert len(tickets) == 1


def test_takeover_capacity_is_isolated_by_business_unit(
    client: TestClient,
) -> None:
    with SessionLocal() as session:
        session.add_all(
            [
                CustomerConversation(
                    business_unit_id="bu_acceptance",
                    requester_ref=f"capacity-acceptance-{index}",
                    status="ACTIVE",
                    assigned_agent_id="agent-1",
                )
                for index in range(5)
            ]
        )
        session.commit()
    conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "requester_ref": "capacity-demo-buyer",
        },
    )
    assert conversation.status_code == 201, conversation.text

    takeover = client.post(
        (
            "/api/v1/customer-service/conversations/"
            f"{conversation.json()['id']}/takeover"
        ),
        headers=AGENT,
        json={"expected_version": conversation.json()["version"]},
    )

    assert takeover.status_code == 200, takeover.text
    assert takeover.json()["assigned_agent_id"] == "agent-1"


def test_test_conversation_archive_hides_it_from_default_list(
    client: TestClient,
) -> None:
    employee = client.post(
        "/api/v1/digital-employees/from-template",
        headers=ADMIN,
        json={
            "name": "测试归档客服",
            "template_code": "enterprise_service_desk",
            "business_unit_id": "bu_demo",
            "knowledge_space_ids": [],
            "skill_ids": [],
            "mcp_connector_ids": [],
            "model_profile": {},
            "change_note": "conversation archive test",
        },
    )
    assert employee.status_code == 201, employee.text
    conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "employee_id": employee.json()["id"],
            "requester_ref": "e2e-conversation-archive",
        },
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]

    listed = client.get(
        "/api/v1/customer-service/conversations?business_unit_id=bu_demo",
        headers=AGENT,
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    archived = client.post(
        (
            "/api/v1/customer-service/conversations/"
            f"{conversation_id}/archive-test-data"
        ),
        headers=ADMIN,
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "ARCHIVED"

    listed_after = client.get(
        "/api/v1/customer-service/conversations?business_unit_id=bu_demo",
        headers=AGENT,
    )
    assert listed_after.status_code == 200
    assert listed_after.json()["total"] == 0
    metrics = client.get(
        "/api/v1/customer-service/metrics?business_unit_id=bu_demo",
        headers=ADMIN,
    )
    assert metrics.status_code == 200
    assert metrics.json()["total_conversations"] == 0
    assert metrics.json()["total_messages"] == 0


def test_enterprise_service_conversation_uses_enterprise_channel(
    client: TestClient,
) -> None:
    employee = client.post(
        "/api/v1/digital-employees/from-template",
        headers=ADMIN,
        json={
            "name": "企业服务台数字员工",
            "template_code": "enterprise_service_desk",
            "business_unit_id": "bu_demo",
            "knowledge_space_ids": [],
            "skill_ids": [],
            "mcp_connector_ids": [],
            "model_profile": {},
            "change_note": "enterprise conversation test",
        },
    )
    assert employee.status_code == 201, employee.text
    employee_id = employee.json()["id"]

    conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "employee_id": employee_id,
            "requester_ref": "enterprise-employee-001",
            "channel": "enterprise_service",
        },
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]

    message = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/messages",
        headers=AGENT,
        json={"content": "请问企业团队消息通知应该如何配置？"},
    )
    assert message.status_code == 202, message.text
    ticket_id = message.json()["current_ticket_id"]
    ticket = client.get(f"/api/v1/tickets/{ticket_id}", headers=AGENT)
    assert ticket.status_code == 200, ticket.text
    payload = ticket.json()
    assert payload["employee"]["id"] == employee_id
    assert payload["source"]["system"] == "enterprise_service_desk"
    assert payload["employee"]["workflow_key"] == "customer_service_ticket_v1"


def test_enterprise_expense_question_is_classified_and_grounded(
    client: TestClient,
) -> None:
    space = client.post(
        "/api/v1/knowledge-spaces",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "code": "enterprise_expense_policy",
            "name": "企业费用与假期制度",
            "description": "费用报销、假期和行政服务流程",
            "domain": "enterprise_service",
            "channel": "enterprise_service",
            "category": "企业服务",
            "workflow_key": "enterprise_service_ticket_v1",
            "owner_id": "admin-1",
        },
    )
    assert space.status_code == 201, space.text
    document = client.post(
        "/api/v1/knowledge-documents",
        headers=ADMIN,
        json={
            "space_id": space.json()["id"],
            "business_unit_id": "bu_demo",
            "title": "企业费用报销与假期申请流程",
            "doc_type": "SOP",
            "owner_id": "admin-1",
            "scope": {"audiences": ["support_agent"]},
        },
    )
    assert document.status_code == 201, document.text
    document_id = document.json()["id"]
    version = client.post(
        f"/api/v1/knowledge-documents/{document_id}/versions",
        headers=ADMIN,
        json={
            "version_label": "1.0",
            "content": (
                "员工报销费用时，应在费用发生后 30 天内于财务系统提交报销单，"
                "附上发票和事由，直属主管审批后由财务复核。"
                "年假和请假需要在 HR 系统提交申请，年假应提前三个工作日申请"
                "并由直属主管审批。"
            ),
            "effective_from": datetime.now(UTC).isoformat(),
        },
    )
    assert version.status_code == 201, version.text
    published = client.post(
        f"/api/v1/knowledge-documents/{document_id}/versions/"
        f"{version.json()['id']}/publish",
        headers=ADMIN,
        json={"release_note": "enterprise expense policy"},
    )
    assert published.status_code == 200, published.text
    skill = client.post(
        "/api/v1/skills",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "code": "enterprise-expense-support",
            "name": "企业费用与假期支持",
            "description": "回答费用报销、发票和假期申请流程。",
            "instructions": "仅依据已发布的企业制度回答，涉及资金动作时转财务人工确认。",
            "triggers": ["报销", "发票", "费用", "年假", "请假"],
            "tools": ["knowledge.search", "ticket.read", "draft.create"],
            "status": "ACTIVE",
        },
    )
    assert skill.status_code == 201, skill.text
    employee = client.post(
        "/api/v1/digital-employees/from-template",
        headers=ADMIN,
        json={
            "name": "费用制度服务台",
            "template_code": "enterprise_service_desk",
            "business_unit_id": "bu_demo",
            "knowledge_space_ids": [space.json()["id"]],
            "skill_ids": [skill.json()["id"]],
            "mcp_connector_ids": [],
            "model_profile": {},
            "change_note": "enterprise expense policy test",
        },
    )
    assert employee.status_code == 201, employee.text
    conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "employee_id": employee.json()["id"],
            "requester_ref": "enterprise-expense-001",
            "channel": "enterprise_service",
        },
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]
    message = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/messages",
        headers=AGENT,
        json={"content": "公司报销流程是什么？"},
    )
    assert message.status_code == 202, message.text
    ticket = client.get(
        f"/api/v1/tickets/{message.json()['current_ticket_id']}",
        headers=AGENT,
    )
    assert ticket.status_code == 200, ticket.text
    payload = ticket.json()
    assert payload["classification"]["primary"] == "billing_invoice"
    assert payload["routing"]["queue_id"] == "FINANCE_SUPPORT"
    assert payload["needs_human"] is True
    assert payload["routing"]["human_reason"] == "POLICY_REQUIRES_HUMAN_REVIEW"

    suggestion = client.post(
        (
            "/api/v1/customer-service/conversations/"
            f"{conversation_id}/reply-suggestions"
        ),
        headers=AGENT,
    )
    assert suggestion.status_code == 200, suggestion.text
    payload = suggestion.json()
    assert payload["skill"] == "enterprise-expense-support"
    assert payload["grounding_status"] == "GROUNDED"
    assert payload["citations"]


def test_reply_suggestion_does_not_append_duplicate_assistant_message(
    client: TestClient,
    monkeypatch,
) -> None:
    employee = client.post(
        "/api/v1/digital-employees/from-template",
        headers=ADMIN,
        json={
            "name": "重复回复回归员工",
            "template_code": "enterprise_service_desk",
            "business_unit_id": "bu_demo",
        },
    )
    assert employee.status_code == 201, employee.text
    conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "employee_id": employee.json()["id"],
            "requester_ref": "reply-suggestion-dedupe-buyer",
            "channel": "enterprise_service",
        },
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]
    accepted = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/messages",
        headers=AGENT,
        json={"content": "办公室门禁失灵了怎么处理？"},
    )
    assert accepted.status_code == 202, accepted.text
    ticket_id = UUID(accepted.json()["current_ticket_id"])
    with SessionLocal() as session:
        ticket = session.get(Ticket, ticket_id)
        assert ticket is not None
        ticket.needs_human = False
        ticket.risk_level = "R0"
        session.commit()

    class _GroundedSuggestionGraph:
        def invoke(self, _state: dict[str, object]) -> dict[str, object]:
            return {
                "draft": DraftResult(
                    text="请通过服务台提交门禁维修申请。",
                    citations=[],
                    claims=[],
                    provider="stub",
                    model="stub-v1",
                    fallback_used=False,
                    grounding_status="GROUNDED",
                ),
                "skill": "stub-skill",
                "trace": ["stub"],
            }

    monkeypatch.setattr(
        CustomerReplySuggestionService,
        "_build_graph",
        lambda self: _GroundedSuggestionGraph(),
    )

    before = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}",
        headers=AGENT,
    )
    assert before.status_code == 200, before.text
    messages_before = before.json()["messages"]

    for _ in range(2):
        suggestion = client.post(
            (
                "/api/v1/customer-service/conversations/"
                f"{conversation_id}/reply-suggestions"
            ),
            headers=AGENT,
        )
        assert suggestion.status_code == 200, suggestion.text
        assert suggestion.json()["text"] == "请通过服务台提交门禁维修申请。"

    after = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}",
        headers=AGENT,
    )
    assert after.status_code == 200, after.text
    assert [
        (message["id"], message["role"], message["content"])
        for message in after.json()["messages"]
    ] == [
        (message["id"], message["role"], message["content"])
        for message in messages_before
    ]


def test_auto_assignment_matches_skill_risk_and_load(
    client: TestClient,
) -> None:
    employee = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json={
            "employee_key": "assignment_employee",
            "name": "自动派单客服",
            "version": "1.0.0",
            "scenario_type": "customer_service_ticket",
            "workflow_key": "customer_service_ticket_v1",
            "business_unit_id": "bu_demo",
            "service_identity": "digital_employee.assignment",
            "handoff_queue": "MANUAL_TRIAGE",
            "tool_allowlist": ["knowledge.search", "draft.create"],
        },
    )
    assert employee.status_code == 201, employee.text
    employee_id = employee.json()["id"]

    def create_ticket(requester: str, content: str) -> tuple[str, str]:
        conversation = client.post(
            "/api/v1/customer-service/conversations",
            headers=AGENT,
            json={
                "business_unit_id": "bu_demo",
                "employee_id": employee_id,
                "requester_ref": requester,
            },
        )
        message = client.post(
            (
                "/api/v1/customer-service/conversations/"
                f"{conversation.json()['id']}/messages"
            ),
            headers=AGENT,
            json={"content": content},
        )
        assert message.status_code == 202, message.text
        return conversation.json()["id"], message.json()["current_ticket_id"]

    presales_conversation, presales_ticket = create_ticket(
        "presales-buyer",
        "这款保温杯容量多少，是什么颜色？",
    )
    aftersales_conversation, aftersales_ticket = create_ticket(
        "aftersales-buyer",
        "订单商品破损，我要申请退款退货。",
    )
    with SessionLocal() as session:
        presales = session.get(Ticket, UUID(presales_ticket))
        aftersales = session.get(Ticket, UUID(aftersales_ticket))
        assert presales is not None and aftersales is not None
        presales.category_primary = "ecommerce_presales"
        presales.risk_level = "R0"
        presales.priority = "P3"
        presales.needs_human = False
        presales.workflow_state = "PENDING_REVIEW"
        aftersales.category_primary = "ecommerce_aftersales"
        aftersales.risk_level = "R2"
        aftersales.priority = "P1"
        aftersales.needs_human = True
        aftersales.workflow_state = "NEEDS_HUMAN"
        session.commit()

    for actor_id, role, skills, clearance in (
        ("presales-agent", "agent", ["ecommerce_presales"], "R1"),
        (
            "risk-supervisor",
            "supervisor",
            ["ecommerce_aftersales"],
            "R3",
        ),
    ):
        heartbeat = client.post(
            "/api/v1/customer-service/presence/heartbeat",
            headers={
                "X-Actor-Id": actor_id,
                "X-Actor-Role": role,
            },
            json={
                "display_name": actor_id,
                "status": "ONLINE",
                "business_unit_id": "bu_demo",
                "skills": skills,
                "risk_clearance": clearance,
                "max_conversations": 5,
            },
        )
        assert heartbeat.status_code == 200, heartbeat.text

    assigned = client.post(
        "/api/v1/customer-service/assignment-queue/auto-assign",
        headers=ADMIN,
    )
    assert assigned.status_code == 200, assigned.text
    by_conversation = {
        item["conversation_id"]: item["agent_id"]
        for item in assigned.json()["assignments"]
    }
    assert by_conversation[presales_conversation] == "presales-agent"
    assert by_conversation[aftersales_conversation] == "risk-supervisor"
    assignment_details = {
        item["conversation_id"]: item
        for item in assigned.json()["assignments"]
    }
    assert "技能匹配" in assignment_details[presales_conversation]["reason"]
    assert "风险权限" in assignment_details[presales_conversation]["reason"]
    presales_candidates = {
        item["agent_id"]: item
        for item in assignment_details[presales_conversation]["candidates"]
    }
    assert presales_candidates["presales-agent"]["selected"] is True
    assert presales_candidates["risk-supervisor"]["eligible"] is False
    assert any(
        "技能不匹配" in reason
        for reason in presales_candidates["risk-supervisor"][
            "excluded_reasons"
        ]
    )


def test_customer_assignment_and_presence_are_tenant_scoped(
    client: TestClient,
) -> None:
    def create_employee(
        business_unit_id: str,
        employee_key: str,
    ) -> str:
        response = client.post(
            "/api/v1/digital-employees",
            headers={
                "X-Actor-Id": "tenant-admin",
                "X-Actor-Role": "admin",
                "X-Business-Unit-Id": business_unit_id,
            },
            json={
                "employee_key": employee_key,
                "name": f"{business_unit_id} 客服员工",
                "version": "1.0.0",
                "scenario_type": "customer_service_ticket",
                "workflow_key": "customer_service_ticket_v1",
                "business_unit_id": business_unit_id,
                "service_identity": f"digital_employee.{employee_key}",
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

    create_employee("bu_demo", "tenant_demo_employee")
    other_employee = create_employee("bu_other", "tenant_other_employee")
    for actor_id, business_unit_id in (
        ("demo-agent-tenant", "bu_demo"),
        ("other-agent-tenant", "bu_other"),
    ):
        heartbeat = client.post(
            "/api/v1/customer-service/presence/heartbeat",
            headers={
                "X-Actor-Id": actor_id,
                "X-Actor-Role": "agent",
                "X-Business-Unit-Id": business_unit_id,
            },
            json={
                "display_name": actor_id,
                "status": "ONLINE",
                "business_unit_id": business_unit_id,
                "skills": ["ecommerce_presales"],
                "risk_clearance": "R2",
                "max_conversations": 5,
            },
        )
        assert heartbeat.status_code == 200, heartbeat.text

    demo_presence = client.get(
        "/api/v1/customer-service/presence",
        headers={
            "X-Actor-Id": "demo-agent-tenant",
            "X-Actor-Role": "agent",
            "X-Business-Unit-Id": "bu_demo",
        },
    )
    assert demo_presence.status_code == 200
    assert [
        item["agent_id"] for item in demo_presence.json()["items"]
    ] == ["demo-agent-tenant"]

    unauthorized_heartbeat = client.post(
        "/api/v1/customer-service/presence/heartbeat",
        headers={
            "X-Actor-Id": "demo-agent-tenant",
            "X-Actor-Role": "agent",
            "X-Business-Unit-Id": "bu_demo",
        },
        json={
            "display_name": "越权客服",
            "status": "ONLINE",
            "business_unit_id": "bu_other",
        },
    )
    assert unauthorized_heartbeat.status_code == 403
    assert (
        unauthorized_heartbeat.json()["code"]
        == "BUSINESS_UNIT_ACCESS_DENIED"
    )

    conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers={
            "X-Actor-Id": "other-agent-tenant",
            "X-Actor-Role": "agent",
            "X-Business-Unit-Id": "bu_other",
        },
        json={
            "business_unit_id": "bu_other",
            "employee_id": other_employee,
            "requester_ref": "other-buyer",
        },
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]
    message = client.post(
        (
            "/api/v1/customer-service/conversations/"
            f"{conversation_id}/messages"
        ),
        headers={
            "X-Actor-Id": "other-agent-tenant",
            "X-Actor-Role": "agent",
            "X-Business-Unit-Id": "bu_other",
        },
        json={"content": "请问这件商品的容量和颜色？"},
    )
    assert message.status_code == 202, message.text

    demo_assign = client.post(
        "/api/v1/customer-service/assignment-queue/auto-assign",
        headers={
            "X-Actor-Id": "demo-agent-tenant",
            "X-Actor-Role": "supervisor",
            "X-Business-Unit-Id": "bu_demo",
        },
    )
    assert demo_assign.status_code == 200, demo_assign.text
    assert demo_assign.json()["assigned_count"] == 0
    still_unassigned = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}",
        headers={
            "X-Actor-Id": "other-agent-tenant",
            "X-Actor-Role": "agent",
            "X-Business-Unit-Id": "bu_other",
        },
    )
    assert still_unassigned.status_code == 200
    assert still_unassigned.json()["assigned_agent_id"] is None

    other_assign = client.post(
        "/api/v1/customer-service/assignment-queue/auto-assign",
        headers={
            "X-Actor-Id": "other-agent-tenant",
            "X-Actor-Role": "supervisor",
            "X-Business-Unit-Id": "bu_other",
        },
    )
    assert other_assign.status_code == 200, other_assign.text
    assignment = next(
        item
        for item in other_assign.json()["assignments"]
        if item["conversation_id"] == conversation_id
    )
    assert assignment["agent_id"] == "other-agent-tenant"
    assert assignment["reason"]
    assert any(
        candidate["agent_id"] == "other-agent-tenant"
        and candidate["selected"]
        for candidate in assignment["candidates"]
    )


def test_reply_suggestion_reports_missing_grounded_knowledge(
    client: TestClient,
) -> None:
    employee = client.post(
        "/api/v1/digital-employees/from-template",
        headers=ADMIN,
        json={
            "name": "无知识售后员工",
            "template_code": "ecommerce_aftersales",
            "business_unit_id": "bu_demo",
        },
    )
    assert employee.status_code == 201, employee.text
    conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "employee_id": employee.json()["id"],
            "requester_ref": "missing-knowledge-buyer",
        },
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]
    message_response = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/messages",
        headers=AGENT,
        json={"content": "商品漏水了，应该怎么处理？"},
    )
    assert message_response.status_code == 202, message_response.text

    suggestion = client.post(
        (
            "/api/v1/customer-service/conversations/"
            f"{conversation_id}/reply-suggestions"
        ),
        headers=AGENT,
    )
    assert suggestion.status_code == 409, suggestion.text
    assert suggestion.json()["code"] == "KNOWLEDGE_NOT_FOUND"
    assert "No knowledge supports" in suggestion.json()["detail"]


def test_conversation_persists_buyer_and_assistant_messages(
    client: TestClient,
) -> None:
    employee = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json={
            "employee_key": "conversation_employee",
            "name": "会话客服",
            "version": "1.0.0",
            "scenario_type": "customer_service_ticket",
            "workflow_key": "customer_service_ticket_v1",
            "business_unit_id": "bu_demo",
            "service_identity": "digital_employee.conversation",
            "handoff_queue": "MANUAL_TRIAGE",
            "tool_allowlist": ["ticket.read", "knowledge.search", "draft.create"],
        },
    )
    assert employee.status_code == 201, employee.text
    conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "employee_id": employee.json()["id"],
            "requester_ref": "buyer-conversation",
        },
    )
    assert conversation.status_code == 201
    conversation_id = conversation.json()["id"]

    accepted = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/messages",
        headers=AGENT,
        json={"content": "如何配置团队消息通知？"},
    )
    assert accepted.status_code == 202, accepted.text
    ticket_id = accepted.json()["current_ticket_id"]
    assert ticket_id
    detail = client.get(f"/api/v1/tickets/{ticket_id}", headers=AGENT)
    assert detail.status_code == 200

    stored = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}",
        headers=AGENT,
    )
    assert stored.status_code == 200
    assert [message["role"] for message in stored.json()["messages"]] == [
        "BUYER",
        "ASSISTANT",
    ]
    assert stored.json()["messages"][1]["ticket_id"] == ticket_id
    assert stored.json()["current_turn"]["status"] == "FAILED_TERMINAL"
    assert stored.json()["current_workflow_state"] == "NEEDS_HUMAN"

    takeover = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/takeover",
        headers=AGENT,
        json={"expected_version": stored.json()["version"]},
    )
    assert takeover.status_code == 200, takeover.text
    assert takeover.json()["assigned_agent_id"] == "agent-1"
    conflict = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/takeover",
        headers={"X-Actor-Id": "agent-2", "X-Actor-Role": "agent"},
        json={"expected_version": takeover.json()["version"]},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "CONVERSATION_ALREADY_ASSIGNED"
    released = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/release",
        headers=AGENT,
    )
    assert released.status_code == 200
    assert released.json()["assigned_agent_id"] is None
    pending_conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "employee_id": employee.json()["id"],
            "requester_ref": "buyer-human-review",
        },
    )
    assert pending_conversation.status_code == 201
    pending_conversation_id = pending_conversation.json()["id"]
    pending = client.post(
        (
            "/api/v1/customer-service/conversations/"
            f"{pending_conversation_id}/messages"
        ),
        headers=AGENT,
        json={"content": "商品不合适，订单怎么申请退货退款？"},
    )
    assert pending.status_code == 202, pending.text
    queue = client.get(
        "/api/v1/customer-service/assignment-queue",
        headers=AGENT,
    )
    assert queue.status_code == 200
    queued_pending = next(
        item
        for item in queue.json()["items"]
        if item["conversation_id"] == pending_conversation_id
    )
    assert queued_pending["priority"] in {"P0", "P1", "P2", "P3"}

    heartbeat = client.post(
        "/api/v1/customer-service/presence/heartbeat",
        headers=AGENT,
        json={
            "display_name": "客服一号",
            "status": "ONLINE",
            "current_conversation_id": conversation_id,
        },
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["online"] is True
    presence = client.get("/api/v1/customer-service/presence", headers=AGENT)
    assert presence.status_code == 200
    assert presence.json()["online_count"] == 1
    assigned = client.post(
        "/api/v1/customer-service/assignment-queue/auto-assign",
        headers=ADMIN,
    )
    assert assigned.status_code == 200, assigned.text
    assigned_pending = next(
        item
        for item in assigned.json()["assignments"]
        if item["conversation_id"] == pending_conversation_id
    )
    assert assigned_pending["agent_id"] == "agent-1"
    with SessionLocal() as session:
        presence_record = session.scalar(
            select(AgentPresence).where(AgentPresence.agent_id == "agent-1")
        )
        assert presence_record is not None
        presence_record.last_seen_at = datetime.now(UTC) - timedelta(minutes=5)
        session.commit()
    reclaimed = client.post(
        "/api/v1/customer-service/presence/reclaim-offline",
        headers=ADMIN,
    )
    assert reclaimed.status_code == 200
    assert reclaimed.json()["reclaimed_count"] >= 1
    queue_after_reclaim = client.get(
        "/api/v1/customer-service/assignment-queue",
        headers=AGENT,
    )
    assert any(
        item["conversation_id"] == pending_conversation_id
        for item in queue_after_reclaim.json()["items"]
    )
    client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/messages",
        headers=AGENT,
        json={"content": "请再确认一下尺码。"},
    )
    with SessionLocal() as session:
        last_message = session.scalar(
            select(CustomerMessage)
            .where(CustomerMessage.conversation_id == UUID(conversation_id))
            .order_by(CustomerMessage.sequence.desc())
            .limit(1)
        )
        assert last_message is not None
        last_message.role = "BUYER"
        last_message.created_at = datetime.now(UTC) - timedelta(minutes=40)
        session.commit()
    alerts = client.get("/api/v1/customer-service/alerts", headers=ADMIN)
    assert alerts.status_code == 200
    assert alerts.json()["total"] == 1
    assert alerts.json()["items"][0]["conversation_id"] == conversation_id
    assert alerts.json()["items"][0]["overdue_seconds"] > 0
    escalated = client.post(
        "/api/v1/customer-service/alerts/escalate",
        headers=ADMIN,
    )
    assert escalated.status_code == 200
    assert escalated.json()["escalated_count"] == 1
    updated_conversation = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}",
        headers=AGENT,
    ).json()
    updated_ticket = client.get(
        f"/api/v1/tickets/{updated_conversation['current_ticket_id']}",
        headers=AGENT,
    ).json()
    assert updated_ticket["priority"]["level"] == "P1"

    notifications = client.post(
        "/api/v1/customer-service/notifications/sync",
        headers=ADMIN,
    )
    assert notifications.status_code == 200
    assert notifications.json()["created_count"] == 1
    notified = client.get(
        "/api/v1/customer-service/notifications",
        headers=ADMIN,
    )
    assert notified.status_code == 200
    assert notified.json()["total"] == 1
    notification_id = notified.json()["items"][0]["id"]
    acknowledged = client.post(
        f"/api/v1/customer-service/notifications/{notification_id}/acknowledge",
        headers=ADMIN,
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json()["status"] == "ACKNOWLEDGED"

    reassigned = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/reassign",
        headers=ADMIN,
        json={
            "expected_version": updated_conversation["version"],
            "agent_id": "agent-2",
            "reason": "SUPERVISOR_TAKEOVER",
        },
    )
    assert reassigned.status_code == 200, reassigned.text
    assert reassigned.json()["assigned_agent_id"] == "agent-2"
    metrics = client.get("/api/v1/customer-service/metrics", headers=ADMIN)
    assert metrics.status_code == 200
    assert metrics.json()["total_conversations"] == 2
    assert metrics.json()["total_messages"] >= 3
    assert metrics.json()["sla_overdue"] == 1
    assert set(metrics.json()["risk_counts"]) == {
        "R0",
        "R1",
        "R2",
        "R3",
        "UNKNOWN",
    }
    assert sum(metrics.json()["risk_counts"].values()) == 2
    history = client.get(
        "/api/v1/customer-service/metrics/history?days=7",
        headers=ADMIN,
    )
    assert history.status_code == 200
    assert history.json()["conversations_created"] == 2
    assert len(history.json()["daily"]) == 7
    assert history.json()["average_first_response_seconds"] is not None


def test_assigned_agent_can_send_manual_reply_and_resolve(
    client: TestClient,
) -> None:
    employee = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json={
            "employee_key": "manual_reply_employee",
            "name": "人工介入客服",
            "version": "1.0.0",
            "scenario_type": "customer_service_ticket",
            "workflow_key": "customer_service_ticket_v1",
            "business_unit_id": "bu_demo",
            "service_identity": "digital_employee.manual_reply",
            "handoff_queue": "MANUAL_TRIAGE",
            "tool_allowlist": ["ticket.read", "knowledge.search", "draft.create"],
        },
    )
    assert employee.status_code == 201, employee.text
    conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "employee_id": employee.json()["id"],
            "requester_ref": "manual-reply-buyer",
        },
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]
    accepted = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/messages",
        headers=AGENT,
        json={"content": "我的商品漏水了，订单怎么申请退货退款？"},
    )
    assert accepted.status_code == 202, accepted.text
    ticket_id = accepted.json()["current_ticket_id"]
    detail = client.get(f"/api/v1/tickets/{ticket_id}", headers=AGENT).json()
    assert detail["workflow_state"] == "NEEDS_HUMAN"
    conversation_detail = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}",
        headers=AGENT,
    )
    assert conversation_detail.status_code == 200
    assert (
        conversation_detail.json()["current_workflow_state"]
        == "NEEDS_HUMAN"
    )
    assert conversation_detail.json()["current_risk_level"] == "R1"

    unassigned_reply = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/manual-replies",
        headers=AGENT,
        json={"content": "我来帮您处理。", "resolve": False},
    )
    assert unassigned_reply.status_code == 409
    assert (
        unassigned_reply.json()["code"]
        == "CONVERSATION_NOT_ASSIGNED_TO_AGENT"
    )

    takeover = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/takeover",
        headers=AGENT,
        json={"expected_version": conversation_detail.json()["version"]},
    )
    assert takeover.status_code == 200, takeover.text
    replied = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/manual-replies",
        headers=AGENT,
        json={"content": "我来帮您核实订单并处理。", "resolve": False},
    )
    assert replied.status_code == 201, replied.text
    assert replied.json()["messages"][-1]["role"] == "ASSISTANT"
    assert replied.json()["messages"][-1]["created_by"] == "agent-1"

    resolved = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/manual-replies",
        headers=AGENT,
        json={"content": "已为您登记退款申请，请留意售后进度。", "resolve": True},
    )
    assert resolved.status_code == 201, resolved.text
    assert resolved.json()["assigned_agent_id"] is None
    assert resolved.json()["current_workflow_state"] == "COMPLETED"
    assert resolved.json()["current_needs_human"] is False
    resolved_messages = resolved.json()["messages"]
    assert resolved_messages[-2]["content"] == "已为您登记退款申请，请留意售后进度。"
    assert resolved_messages[-2]["created_by"] == "agent-1"
    assert "会话已交还数字员工" in resolved_messages[-1]["content"]
    duplicate_resolution = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/manual-replies",
        headers=AGENT,
        json={"content": "重复完成", "resolve": True},
    )
    assert duplicate_resolution.status_code == 409
    assert (
        duplicate_resolution.json()["code"]
        == "CONVERSATION_NOT_ASSIGNED_TO_AGENT"
    )
    final_ticket = client.get(f"/api/v1/tickets/{ticket_id}", headers=AGENT).json()
    assert final_ticket["workflow_state"] == "COMPLETED"
    assert final_ticket["status"] == "RESOLVED"
    assert final_ticket["needs_human"] is False
    next_turn = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/messages",
        headers=AGENT,
        json={"content": "还有别的售后问题"},
    )
    assert next_turn.status_code == 202
    assert next_turn.json()["current_ticket_id"] == ticket_id
    # The response is rendered before the queued worker runs, so the new turn
    # is either still queued or already claimed.
    assert next_turn.json()["current_turn"]["status"] in {
        "PENDING",
        "RUNNING",
    }


def test_completed_conversation_reroutes_new_question_and_keeps_history(
    client: TestClient,
) -> None:
    def create_employee(employee_key: str, name: str) -> dict[str, object]:
        response = client.post(
            "/api/v1/digital-employees",
            headers=ADMIN,
            json={
                "employee_key": employee_key,
                "name": name,
                "version": "1.0.0",
                "scenario_type": "customer_service_ticket",
                "workflow_key": "customer_service_ticket_v1",
                "business_unit_id": "bu_demo",
                "service_identity": f"digital_employee.{employee_key}",
                "handoff_queue": "MANUAL_TRIAGE",
                "tool_allowlist": [
                    "ticket.read",
                    "knowledge.search",
                    "draft.create",
                ],
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    complaint_agent = create_employee(
        "handoff_complaint_agent",
        "投诉处理数字员工",
    )
    developer_agent = create_employee(
        "handoff_developer_agent",
        "研发支持数字员工",
    )
    complaint_rule = client.put(
        f"/api/v1/digital-employees/{complaint_agent['id']}/route-rule",
        headers=ADMIN,
        json={
            "intents": ["投诉", "退款", "赔偿"],
            "categories": [],
            "channels": [],
            "priority": 10,
            "fallback": False,
            "enabled": True,
        },
    )
    assert complaint_rule.status_code == 200, complaint_rule.text
    developer_rule = client.put(
        f"/api/v1/digital-employees/{developer_agent['id']}/route-rule",
        headers=ADMIN,
        json={
            "intents": ["GitHub", "仓库文档", "安全限制", "研发支持"],
            "categories": [],
            "channels": [],
            "priority": 20,
            "fallback": False,
            "enabled": True,
        },
    )
    assert developer_rule.status_code == 200, developer_rule.text
    service_entry = client.post(
        "/api/v1/business-service-entries",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "code": "handoff_reroute_entry",
            "name": "企业综合服务台",
            "description": "投诉和研发支持统一入口",
            "domain": "customer_service",
            "channel": "enterprise_service",
            "default_employee_id": complaint_agent["id"],
            "fallback_employee_id": complaint_agent["id"],
            "human_queue_id": "ENTERPRISE_SERVICE_HUMAN",
            "employees": [
                {
                    "employee_id": complaint_agent["id"],
                    "role_type": "PRIMARY",
                    "priority": 10,
                },
                {
                    "employee_id": developer_agent["id"],
                    "role_type": "SPECIALIST",
                    "priority": 20,
                },
            ],
        },
    )
    assert service_entry.status_code == 201, service_entry.text
    conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "service_entry_id": service_entry.json()["id"],
            "requester_ref": "handoff-reroute-buyer",
            "channel": "enterprise_service",
        },
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]
    first = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/messages",
        headers=AGENT,
        json={"content": "我要投诉并申请退款赔偿"},
    )
    assert first.status_code == 202, first.text
    ticket_id = first.json()["current_ticket_id"]
    first_ticket = client.get(
        f"/api/v1/tickets/{ticket_id}",
        headers=AGENT,
    ).json()
    assert first_ticket["employee"]["id"] == complaint_agent["id"]
    detail = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}",
        headers=AGENT,
    ).json()
    takeover = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/takeover",
        headers=AGENT,
        json={"expected_version": detail["version"]},
    )
    assert takeover.status_code == 200, takeover.text
    completed = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/manual-replies",
        headers=AGENT,
        json={
            "content": "投诉已登记，退款申请已提交财务复核。",
            "resolve": True,
        },
    )
    assert completed.status_code == 201, completed.text
    assert completed.json()["assigned_agent_id"] is None
    assert completed.json()["current_workflow_state"] == "COMPLETED"

    second = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/messages",
        headers=AGENT,
        json={"content": "查询公开 GitHub 仓库文档有哪些安全限制？"},
    )
    assert second.status_code == 202, second.text
    assert second.json()["current_ticket_id"] == ticket_id
    assert second.json()["employee_id"] == developer_agent["id"]
    assert second.json()["current_turn"]["employee_id"] == developer_agent["id"]
    second_ticket = client.get(
        f"/api/v1/tickets/{ticket_id}",
        headers=AGENT,
    ).json()
    assert second_ticket["employee"]["id"] == developer_agent["id"]
    assert [
        message["content"]
        for message in second.json()["messages"]
        if "投诉已登记" in message["content"]
        or "会话已交还数字员工" in message["content"]
    ] == [
        "投诉已登记，退款申请已提交财务复核。",
        "人工处理已完成，会话已交还数字员工。后续问题将继续由数字员工接待。",
    ]
    with SessionLocal() as session:
        decisions = list(
            session.scalars(
                select(DigitalEmployeeRouteDecision).where(
                    DigitalEmployeeRouteDecision.conversation_id
                    == UUID(conversation_id)
                )
            ).all()
        )
    assert any(
        decision.ticket_id == UUID(ticket_id)
        and str(decision.selected_employee_id) == developer_agent["id"]
        for decision in decisions
    )


def test_active_conversation_reroutes_when_topic_changes(
    client: TestClient,
) -> None:
    def create_employee(employee_key: str, name: str) -> dict[str, object]:
        response = client.post(
            "/api/v1/digital-employees",
            headers=ADMIN,
            json={
                "employee_key": employee_key,
                "name": name,
                "version": "1.0.0",
                "scenario_type": "enterprise_service",
                "workflow_key": "customer_service_ticket_v1",
                "business_unit_id": "bu_demo",
                "service_identity": f"digital_employee.{employee_key}",
                "handoff_queue": "MANUAL_TRIAGE",
                "tool_allowlist": [
                    "ticket.read",
                    "knowledge.search",
                    "draft.create",
                ],
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    enterprise_agent = create_employee(
        "active_topic_enterprise",
        "企业服务数字员工",
    )
    developer_agent = create_employee(
        "active_topic_developer",
        "研发支持数字员工",
    )
    enterprise_rule = client.put(
        f"/api/v1/digital-employees/{enterprise_agent['id']}/route-rule",
        headers=ADMIN,
        json={
            "intents": ["通知", "配置", "账号"],
            "categories": [],
            "channels": [],
            "priority": 10,
            "fallback": False,
            "enabled": True,
        },
    )
    assert enterprise_rule.status_code == 200, enterprise_rule.text
    developer_rule = client.put(
        f"/api/v1/digital-employees/{developer_agent['id']}/route-rule",
        headers=ADMIN,
        json={
            "intents": ["GitHub", "仓库", "模块", "依赖关系", "SDK"],
            "categories": [],
            "channels": [],
            "priority": 10,
            "fallback": False,
            "enabled": True,
        },
    )
    assert developer_rule.status_code == 200, developer_rule.text
    service_entry = client.post(
        "/api/v1/business-service-entries",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "code": "active_topic_entry",
            "name": "跨专业续聊入口",
            "description": "同一会话中根据新问题重新选员工",
            "domain": "enterprise_service",
            "channel": "enterprise_service",
            "default_employee_id": enterprise_agent["id"],
            "fallback_employee_id": enterprise_agent["id"],
            "human_queue_id": "MANUAL_TRIAGE",
            "employees": [
                {
                    "employee_id": enterprise_agent["id"],
                    "role_type": "PRIMARY",
                    "priority": 10,
                },
                {
                    "employee_id": developer_agent["id"],
                    "role_type": "SPECIALIST",
                    "priority": 20,
                },
            ],
        },
    )
    assert service_entry.status_code == 201, service_entry.text
    conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "service_entry_id": service_entry.json()["id"],
            "requester_ref": "active-topic-buyer",
            "channel": "enterprise_service",
        },
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]
    first = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/messages",
        headers=AGENT,
        json={"content": "如何配置团队消息通知？"},
    )
    assert first.status_code == 202, first.text
    ticket_id = first.json()["current_ticket_id"]
    first_ticket = client.get(
        f"/api/v1/tickets/{ticket_id}",
        headers=AGENT,
    ).json()
    assert first_ticket["employee"]["id"] == enterprise_agent["id"]

    second = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/messages",
        headers=AGENT,
        json={
            "content": (
                "请查询 modelcontextprotocol/python-sdk 的模块和依赖关系"
            )
        },
    )
    assert second.status_code == 202, second.text
    assert second.json()["current_ticket_id"] == ticket_id
    second_ticket = client.get(
        f"/api/v1/tickets/{ticket_id}",
        headers=AGENT,
    ).json()
    assert second_ticket["employee"]["id"] == developer_agent["id"]


def test_technical_question_without_tool_does_not_use_generic_template(
    client: TestClient,
) -> None:
    employee = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json={
            "employee_key": "technical_evidence_gate_employee",
            "name": "研发支持数字员工",
            "version": "1.0.0",
            "scenario_type": "enterprise_service",
            "workflow_key": "customer_service_ticket_v1",
            "business_unit_id": "bu_demo",
            "service_identity": "digital_employee.technical_evidence_gate",
            "handoff_queue": "MANUAL_TRIAGE",
            "tool_allowlist": [
                "ticket.read",
                "knowledge.search",
                "draft.create",
            ],
        },
    )
    assert employee.status_code == 201, employee.text
    skill = client.post(
        "/api/v1/skills",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "code": "developer-repository-support",
            "name": "研发仓库支持",
            "description": "查询公开仓库文档、模块和依赖关系。",
            "instructions": (
                "只使用公开仓库、已发布技术和获准只读工具；"
                "没有证据时明确说明，不生成产品配置模板。"
            ),
            "triggers": ["GitHub", "仓库", "模块", "依赖关系", "SDK"],
            "tools": ["knowledge.search", "draft.create"],
        },
    )
    assert skill.status_code == 201, skill.text
    bound = client.put(
        f"/api/v1/digital-employees/{employee.json()['id']}/skills",
        headers=ADMIN,
        json={
            "bindings": [
                {
                    "skill_id": skill.json()["id"],
                    "enabled": True,
                    "priority": 10,
                }
            ]
        },
    )
    assert bound.status_code == 200, bound.text
    conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "employee_id": employee.json()["id"],
            "requester_ref": "technical-evidence-gate-buyer",
            "channel": "enterprise_service",
        },
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]
    technical = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/messages",
        headers=AGENT,
        json={
            "content": (
                "请查询 modelcontextprotocol/python-sdk "
                "的主要模块和依赖关系，并说明依据。"
            )
        },
    )
    assert technical.status_code == 202, technical.text
    detail = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}",
        headers=AGENT,
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["current_turn"]["intent"] == "product_howto"
    assert payload["current_turn"]["response_provider"] == "system_policy"
    assert (
        payload["current_turn"]["response_model"]
        == "technical-evidence-gate-v1"
    )
    assert payload["current_turn"]["grounding_status"] == "NO_KNOWLEDGE"
    assert payload["current_turn"]["citations"] == []
    answer = payload["messages"][-1]["content"]
    assert "modelcontextprotocol/python-sdk" in answer
    assert "DeepWiki" in answer
    assert "产品配置" not in answer
    assert "产品支持组" not in answer

    follow_up = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/messages",
        headers=AGENT,
        json={"content": "它有哪些依赖关系？"},
    )
    assert follow_up.status_code == 202, follow_up.text
    follow_up_payload = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}",
        headers=AGENT,
    ).json()
    follow_up_answer = follow_up_payload["messages"][-1]["content"]
    assert "modelcontextprotocol/python-sdk" in follow_up_answer
    assert "缺少可用于回答的公开仓库地址" not in follow_up_answer

    identity = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/messages",
        headers=AGENT,
        json={"content": "你是谁"},
    )
    assert identity.status_code == 202, identity.text
    identity_payload = identity.json()
    assert identity_payload["current_turn"]["intent"] == "small_talk"
    assert (
        identity_payload["current_turn"]["response_model"]
        == "employee-self-introduction-v1"
    )
    assert "研发支持数字员工" in identity_payload["messages"][-1]["content"]
    assert "产品支持组" not in identity_payload["messages"][-1]["content"]


def _read_sse_stream(response: object) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    event_name = ""
    data_lines: list[str] = []
    for raw_line in response.iter_lines():  # type: ignore[attr-defined]
        line = raw_line if isinstance(raw_line, str) else raw_line.decode()
        if line.startswith("event: "):
            event_name = line[len("event: ") :]
        elif line.startswith("data: "):
            data_lines.append(line[len("data: ") :])
        elif not line:
            if data_lines:
                payload = json.loads("\n".join(data_lines))
                payload.setdefault("type", event_name)
                events.append(payload)
            event_name = ""
            data_lines = []
    return events


def test_streaming_message_returns_live_stage_and_text_events(
    client: TestClient,
) -> None:
    space = client.post(
        "/api/v1/knowledge-spaces",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "code": "streaming_expense_policy",
            "name": "流式测试费用制度",
            "description": "费用报销流程",
            "domain": "enterprise_service",
            "channel": "enterprise_service",
            "category": "企业服务",
            "workflow_key": "enterprise_service_ticket_v1",
            "owner_id": "admin-1",
        },
    )
    assert space.status_code == 201, space.text
    document = client.post(
        "/api/v1/knowledge-documents",
        headers=ADMIN,
        json={
            "space_id": space.json()["id"],
            "business_unit_id": "bu_demo",
            "title": "企业费用报销流程",
            "doc_type": "SOP",
            "owner_id": "admin-1",
            "scope": {"audiences": ["support_agent"]},
        },
    )
    assert document.status_code == 201, document.text
    document_id = document.json()["id"]
    version = client.post(
        f"/api/v1/knowledge-documents/{document_id}/versions",
        headers=ADMIN,
        json={
            "version_label": "1.0",
            "content": (
                "员工报销费用时，应在费用发生后 30 天内于财务系统提交报销单，"
                "附上发票和事由，直属主管审批后由财务复核。"
            ),
            "effective_from": datetime.now(UTC).isoformat(),
        },
    )
    assert version.status_code == 201, version.text
    published = client.post(
        f"/api/v1/knowledge-documents/{document_id}/versions/"
        f"{version.json()['id']}/publish",
        headers=ADMIN,
        json={"release_note": "streaming policy"},
    )
    assert published.status_code == 200, published.text
    employee = client.post(
        "/api/v1/digital-employees/from-template",
        headers=ADMIN,
        json={
            "name": "企业服务台流式数字员工",
            "template_code": "enterprise_service_desk",
            "business_unit_id": "bu_demo",
            "knowledge_space_ids": [space.json()["id"]],
            "skill_ids": [],
            "mcp_connector_ids": [],
            "model_profile": {},
            "change_note": "streaming conversation test",
        },
    )
    assert employee.status_code == 201, employee.text

    conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "employee_id": employee.json()["id"],
            "requester_ref": "streaming-enterprise-001",
            "channel": "enterprise_service",
        },
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]

    with client.stream(
        "POST",
        f"/api/v1/customer-service/conversations/{conversation_id}/messages/stream",
        headers=AGENT,
        json={"content": "公司报销流程是什么？"},
    ) as response:
        assert response.status_code == 200, response.read()
        events = _read_sse_stream(response)

    event_types = [str(event["type"]) for event in events]
    assert event_types[0] == "start"
    assert event_types[-1] == "done"
    assert "status" in event_types
    assert "delta" in event_types

    stages = [
        str(event["stage"]) for event in events if event["type"] == "status"
    ]
    assert stages[0] == "正在识别问题"
    assert any("检索" in stage for stage in stages)

    streamed_text = "".join(
        str(event["text"]) for event in events if event["type"] == "delta"
    )
    assert streamed_text

    done = events[-1]
    final_conversation = done["conversation"]
    assert isinstance(final_conversation, dict)
    assistant = [
        message
        for message in final_conversation["messages"]
        if message["role"] == "ASSISTANT"
    ][-1]
    assert assistant["created_by"] == "digital_employee"
    assert assistant["content"] == streamed_text
    assert final_conversation["current_turn"]["status"] == "COMPLETED"


def test_streaming_small_talk_returns_start_and_done_without_deltas(
    client: TestClient,
) -> None:
    conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "requester_ref": "streaming-small-talk",
            "channel": "enterprise_service",
        },
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]

    with client.stream(
        "POST",
        f"/api/v1/customer-service/conversations/{conversation_id}/messages/stream",
        headers=AGENT,
        json={"content": "你好"},
    ) as response:
        assert response.status_code == 200, response.read()
        events = _read_sse_stream(response)

    assert [event["type"] for event in events] == ["start", "done"]
    final_conversation = events[-1]["conversation"]
    assert isinstance(final_conversation, dict)
    assert [message["role"] for message in final_conversation["messages"]] == [
        "BUYER",
        "ASSISTANT",
    ]


def test_first_message_after_takeover_creates_a_human_owned_ticket(
    client: TestClient,
) -> None:
    conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "requester_ref": "taken-over-before-first-message",
        },
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]

    # The operator takes the conversation before the buyer has said anything,
    # so there is no ticket to move yet.
    takeover = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/takeover",
        headers=AGENT,
        json={"expected_version": conversation.json()["version"]},
    )
    assert takeover.status_code == 200, takeover.text
    assert takeover.json()["current_ticket_id"] is None

    accepted = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/messages",
        headers=AGENT,
        json={"content": "保温杯内胆是什么材质？"},
    )
    assert accepted.status_code == 202, accepted.text
    view = accepted.json()
    assert view["current_turn"]["status"] == "NEEDS_HUMAN"
    ticket_id = view["current_ticket_id"]
    assert ticket_id is not None

    ticket = client.get(f"/api/v1/tickets/{ticket_id}", headers=AGENT)
    assert ticket.status_code == 200, ticket.text
    assert ticket.json()["workflow_state"] == "NEEDS_HUMAN"
    assert ticket.json()["status"] == "WAITING_HUMAN"
    assert ticket.json()["needs_human"] is True

    # The workbench reply is accepted, which is the point of the ticket state.
    reply = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}"
        "/manual-replies",
        headers=AGENT,
        json={"content": "内胆为 316 不锈钢。", "resolve": True},
    )
    assert reply.status_code == 201, reply.text
    assert reply.json()["assigned_agent_id"] is None

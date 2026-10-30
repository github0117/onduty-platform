"""Sticky employee routing for an existing conversation.

A conversation belongs to an employee. The entry router may move it, but only
for a reason that survives more than one ambiguous message: an explicit
request, a finished ticket, a genuine capability gap or the same recommendation
on consecutive turns. These tests drive the real API and assert the stored
conversation, handoff and route decision.
"""

from collections.abc import Generator
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ticket_agent.customer_service.models import (
    ConversationHandoff,
    CustomerConversation,
)
from ticket_agent.digital_employees.models import DigitalEmployeeRouteDecision
from ticket_agent.shared.db import SessionLocal
from ticket_agent.shared.settings import get_settings


@pytest.fixture(autouse=True)
def _fresh_settings() -> Generator[None, None, None]:
    """``get_settings`` is cached; tests that change thresholds must rebuild it."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _set_strong_margin(monkeypatch: Any, value: str) -> None:
    monkeypatch.setenv("CONVERSATION_REROUTE_STRONG_MARGIN", value)
    get_settings.cache_clear()

ADMIN = {"X-Actor-Id": "stickiness-admin", "X-Actor-Role": "admin"}
AGENT = {"X-Actor-Id": "stickiness-agent", "X-Actor-Role": "agent"}
SUPERVISOR = {
    "X-Actor-Id": "stickiness-supervisor",
    "X-Actor-Role": "supervisor",
}


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


def _rule(
    client: TestClient,
    employee_id: str,
    *,
    intents: list[str],
    priority: int = 10,
) -> None:
    response = client.put(
        f"/api/v1/digital-employees/{employee_id}/route-rule",
        headers=ADMIN,
        json={
            "intents": intents,
            "categories": [],
            "channels": [],
            "priority": priority,
            "fallback": False,
            "enabled": True,
        },
    )
    assert response.status_code == 200, response.text


def _entry(
    client: TestClient,
    *,
    code: str,
    default_employee_id: str,
    employee_ids: list[str],
) -> str:
    response = client.post(
        "/api/v1/business-service-entries",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "code": code,
            "name": "粘性路由测试入口",
            "description": "验证会话不会逐条消息换人",
            "domain": "customer_service",
            "channel": "enterprise_service",
            "default_employee_id": default_employee_id,
            "fallback_employee_id": default_employee_id,
            "human_queue_id": "ENTERPRISE_SERVICE_HUMAN",
            "employees": [
                {
                    "employee_id": employee_id,
                    "role_type": (
                        "PRIMARY"
                        if employee_id == default_employee_id
                        else "SPECIALIST"
                    ),
                    "priority": index * 10,
                }
                for index, employee_id in enumerate(employee_ids, start=1)
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _conversation(client: TestClient, entry_id: str) -> str:
    response = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "service_entry_id": entry_id,
            "requester_ref": f"sticky-buyer-{entry_id}",
            "channel": "enterprise_service",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _send(client: TestClient, conversation_id: str, content: str) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/messages",
        headers=AGENT,
        json={"content": content},
    )
    assert response.status_code == 202, response.text
    return dict(response.json())


def _detail(client: TestClient, conversation_id: str) -> dict[str, Any]:
    response = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}",
        headers=AGENT,
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def _logistics_and_refund_employees(
    client: TestClient,
    *,
    suffix: str,
) -> tuple[str, str]:
    logistics = _employee(client, f"sticky_logistics_{suffix}", "物流客服")
    refund = _employee(client, f"sticky_refund_{suffix}", "退款客服")
    _rule(client, logistics, intents=["物流", "快递", "配送", "发货"])
    _rule(client, refund, intents=["退款", "退货", "售后"])
    return logistics, refund


def _decision_for(conversation_id: str) -> DigitalEmployeeRouteDecision | None:
    with SessionLocal() as session:
        return session.scalar(
            select(DigitalEmployeeRouteDecision)
            .where(
                DigitalEmployeeRouteDecision.conversation_id
                == UUID(conversation_id)
            )
            .order_by(DigitalEmployeeRouteDecision.created_at.desc())
            .limit(1)
        )


def test_first_message_assigns_employee_and_later_ambiguous_message_keeps_it(
    client: TestClient,
    monkeypatch: Any,
) -> None:
    _set_strong_margin(monkeypatch, "0.99")
    logistics, refund = _logistics_and_refund_employees(
        client, suffix="ambiguous"
    )
    entry = _entry(
        client,
        code="sticky_entry_ambiguous",
        default_employee_id=logistics,
        employee_ids=[logistics, refund],
    )
    conversation_id = _conversation(client, entry)

    first = _send(client, conversation_id, "我的快递怎么一直没到")
    assert first["employee_id"] == logistics

    _send(client, conversation_id, "我要退款")

    detail = _detail(client, conversation_id)
    assert detail["employee_id"] == logistics
    assert detail["latest_handoff"] is None
    decision = _decision_for(conversation_id)
    assert decision is not None
    # The router saw the refund topic but kept the conversation.
    assert decision.reason_code == "STICKY_CURRENT"


def test_capability_gap_switches_immediately(
    client: TestClient,
    monkeypatch: Any,
) -> None:
    _set_strong_margin(monkeypatch, "0.05")
    logistics, refund = _logistics_and_refund_employees(
        client, suffix="gap"
    )
    entry = _entry(
        client,
        code="sticky_entry_gap",
        default_employee_id=logistics,
        employee_ids=[logistics, refund],
    )
    conversation_id = _conversation(client, entry)
    _send(client, conversation_id, "我的快递怎么一直没到")

    _send(client, conversation_id, "我要退款")

    detail = _detail(client, conversation_id)
    assert detail["employee_id"] == refund
    assert detail["employee_source"] == "AUTO_HANDOFF"
    handoff = detail["latest_handoff"]
    assert handoff["kind"] == "AUTO_REROUTE"
    assert handoff["reason_code"] == "CAPABILITY_GAP"
    # The record must name the employee the turn started with, not the one
    # the reroute just selected.
    assert handoff["from_employee_id"] == logistics
    assert handoff["to_employee_id"] == refund


def test_sustained_topic_switches_on_the_second_consecutive_message(
    client: TestClient,
    monkeypatch: Any,
) -> None:
    _set_strong_margin(monkeypatch, "0.99")
    logistics, refund = _logistics_and_refund_employees(
        client, suffix="sustained"
    )
    entry = _entry(
        client,
        code="sticky_entry_sustained",
        default_employee_id=logistics,
        employee_ids=[logistics, refund],
    )
    conversation_id = _conversation(client, entry)
    _send(client, conversation_id, "我的快递怎么一直没到")

    _send(client, conversation_id, "我要退款")
    assert _detail(client, conversation_id)["employee_id"] == logistics

    _send(client, conversation_id, "退款要怎么申请")
    detail = _detail(client, conversation_id)
    assert detail["employee_id"] == refund
    assert detail["latest_handoff"]["reason_code"] == "SUSTAINED_TOPIC"


def test_explicit_request_switches_on_the_first_message(
    client: TestClient,
    monkeypatch: Any,
) -> None:
    _set_strong_margin(monkeypatch, "0.99")
    logistics, refund = _logistics_and_refund_employees(
        client, suffix="explicit"
    )
    entry = _entry(
        client,
        code="sticky_entry_explicit",
        default_employee_id=logistics,
        employee_ids=[logistics, refund],
    )
    conversation_id = _conversation(client, entry)
    _send(client, conversation_id, "我的快递怎么一直没到")

    _send(client, conversation_id, "请帮我转接售后同事")

    detail = _detail(client, conversation_id)
    assert detail["employee_id"] == refund
    assert detail["latest_handoff"]["reason_code"] == "EXPLICIT_REQUEST"


def test_manual_switch_locks_the_conversation_against_the_router(
    client: TestClient,
    monkeypatch: Any,
) -> None:
    _set_strong_margin(monkeypatch, "0.05")
    logistics, refund = _logistics_and_refund_employees(
        client, suffix="manual"
    )
    entry = _entry(
        client,
        code="sticky_entry_manual",
        default_employee_id=logistics,
        employee_ids=[logistics, refund],
    )
    conversation_id = _conversation(client, entry)
    _send(client, conversation_id, "我的快递怎么一直没到")

    # A supervisor moves the conversation; the router must not take it back.
    switched = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/employee",
        headers=SUPERVISOR,
        json={"employee_id": refund, "reason": "主管指定退款同事"},
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["employee_source"] == "MANUAL"

    _send(client, conversation_id, "我的快递到底到哪了")

    detail = _detail(client, conversation_id)
    assert detail["employee_id"] == refund
    assert detail["employee_source"] == "MANUAL"
    assert detail["latest_handoff"]["kind"] == "OPERATOR_SWITCH"
    with SessionLocal() as session:
        auto = session.scalar(
            select(ConversationHandoff).where(
                ConversationHandoff.kind == "AUTO_REROUTE"
            )
        )
    assert auto is None


def test_cooldown_and_switch_cap_bound_automatic_reroutes(
    client: TestClient,
    monkeypatch: Any,
) -> None:
    _set_strong_margin(monkeypatch, "0.05")
    logistics, refund = _logistics_and_refund_employees(
        client, suffix="cooldown"
    )
    entry = _entry(
        client,
        code="sticky_entry_cooldown",
        default_employee_id=logistics,
        employee_ids=[logistics, refund],
    )
    conversation_id = _conversation(client, entry)
    _send(client, conversation_id, "我的快递怎么一直没到")

    _send(client, conversation_id, "我要退款")  # switch 1 at sequence 2
    assert _detail(client, conversation_id)["employee_id"] == refund

    _send(client, conversation_id, "快递到哪了")  # too soon
    assert _detail(client, conversation_id)["employee_id"] == refund
    _send(client, conversation_id, "快递还没到")  # still too soon
    assert _detail(client, conversation_id)["employee_id"] == refund

    _send(client, conversation_id, "快递呢")  # sequence 5, cooldown over
    assert _detail(client, conversation_id)["employee_id"] == logistics

    _send(client, conversation_id, "我要退款")  # third switch is capped
    detail = _detail(client, conversation_id)
    assert detail["employee_id"] == logistics
    with SessionLocal() as session:
        conversation = session.get(
            CustomerConversation,
            UUID(conversation_id),
        )
        assert conversation is not None
        assert conversation.auto_reroute_count == 2


def test_conversation_without_service_entry_never_reroutes(
    client: TestClient,
) -> None:
    logistics, refund = _logistics_and_refund_employees(
        client, suffix="no_entry"
    )
    response = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "employee_id": logistics,
            "requester_ref": "sticky-buyer-no-entry",
        },
    )
    assert response.status_code == 201, response.text
    conversation_id = response.json()["id"]
    _send(client, conversation_id, "我要退款")

    detail = _detail(client, conversation_id)
    assert detail["employee_id"] == logistics
    assert detail["latest_handoff"] is None

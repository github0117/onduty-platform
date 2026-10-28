from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ticket_agent.customer_service.models import CustomerConversation
from ticket_agent.model_gateway.models import ModelCall
from ticket_agent.shared.db import SessionLocal
from ticket_agent.tickets.models import AnswerDraft, Ticket

BUSINESS_MANAGER = {
    "X-Actor-Id": "business-manager-value",
    "X-Actor-Role": "business_manager",
    "X-Business-Unit-Id": "bu_demo",
}


def _ticket(
    session,
    *,
    business_unit_id: str,
    created_at: datetime,
) -> Ticket:
    ticket = Ticket(
        business_unit_id=business_unit_id,
        source_system="value_metrics_test",
        source_ticket_id=f"VM-{uuid4()}",
        source_channel="web_form",
        idempotency_key=f"value-metrics-{uuid4()}",
        request_hash="0" * 64,
        requester_ref="value-customer",
        subject="价值指标测试工单",
        body="用于统计采纳率与成本。",
        created_at=created_at,
    )
    session.add(ticket)
    session.flush()
    return ticket


def _draft(
    session,
    *,
    ticket: Ticket,
    status: str,
    grounding_status: str,
    created_at: datetime,
) -> None:
    session.add(
        AnswerDraft(
            ticket_id=ticket.id,
            text="价值指标测试草稿",
            status=status,
            grounding_status=grounding_status,
            created_at=created_at,
        )
    )


def _model_call(
    session,
    *,
    business_unit_id: str,
    started_at: datetime,
    tokens: int,
    cost: float,
) -> None:
    session.add(
        ModelCall(
            business_unit_id=business_unit_id,
            correlation_id=f"value-{uuid4()}",
            purpose="classification",
            provider="openai_compatible",
            model_name="classifier",
            status="SUCCEEDED",
            input_tokens=tokens,
            output_tokens=0,
            total_tokens=tokens,
            estimated_cost=cost,
            latency_ms=10,
            started_at=started_at,
            completed_at=started_at,
        )
    )


def _conversation(
    session,
    *,
    business_unit_id: str,
    created_at: datetime,
    status: str = "ACTIVE",
) -> None:
    session.add(
        CustomerConversation(
            business_unit_id=business_unit_id,
            requester_ref="value-customer",
            status=status,
            created_at=created_at,
        )
    )


def _seed(session, now: datetime) -> None:
    recent = _ticket(session, business_unit_id="bu_demo", created_at=now)
    for status, grounding in (
        ("ACCEPTED", "GROUNDED"),
        ("ACCEPTED", "GROUNDED"),
        ("EDITED_AND_ACCEPTED", "GROUNDED"),
        ("EDITED_AND_ACCEPTED", "GROUNDED"),
        ("REJECTED", "NO_KNOWLEDGE"),
        ("ESCALATED", "NO_KNOWLEDGE"),
        ("NEEDS_REVIEW", "UNVERIFIED"),
        ("AUTO_ACCEPTED", "GROUNDED"),
        ("AUTO_ACCEPTED", "GROUNDED"),
    ):
        _draft(
            session,
            ticket=recent,
            status=status,
            grounding_status=grounding,
            created_at=now,
        )
    _ticket(session, business_unit_id="bu_demo", created_at=now - timedelta(days=1))
    ten_days_ago_ticket = _ticket(
        session, business_unit_id="bu_demo", created_at=now - timedelta(days=10)
    )
    _draft(
        session,
        ticket=ten_days_ago_ticket,
        status="ACCEPTED",
        grounding_status="GROUNDED",
        created_at=now - timedelta(days=10),
    )
    old_ticket = _ticket(
        session, business_unit_id="bu_demo", created_at=now - timedelta(days=40)
    )
    _draft(
        session,
        ticket=old_ticket,
        status="ACCEPTED",
        grounding_status="GROUNDED",
        created_at=now - timedelta(days=40),
    )
    other_ticket = _ticket(
        session, business_unit_id="bu_other", created_at=now
    )
    _draft(
        session,
        ticket=other_ticket,
        status="ACCEPTED",
        grounding_status="GROUNDED",
        created_at=now,
    )

    _conversation(session, business_unit_id="bu_demo", created_at=now)
    _conversation(
        session,
        business_unit_id="bu_demo",
        created_at=now,
        status="ARCHIVED",
    )
    _conversation(
        session, business_unit_id="bu_demo", created_at=now - timedelta(days=2)
    )
    _conversation(session, business_unit_id="bu_other", created_at=now)
    _conversation(
        session,
        business_unit_id="bu_demo",
        created_at=now - timedelta(days=40),
    )

    _model_call(
        session, business_unit_id="bu_demo", started_at=now, tokens=100, cost=0.02
    )
    _model_call(
        session, business_unit_id="bu_demo", started_at=now, tokens=200, cost=0.01
    )
    _model_call(
        session,
        business_unit_id="bu_demo",
        started_at=now - timedelta(days=10),
        tokens=50,
        cost=0.005,
    )
    _model_call(
        session,
        business_unit_id="bu_demo",
        started_at=now - timedelta(days=40),
        tokens=10,
        cost=0.001,
    )
    _model_call(
        session, business_unit_id="bu_other", started_at=now, tokens=999, cost=9.0
    )


def test_value_metrics_aggregate_adoption_and_cost(client: TestClient) -> None:
    now = datetime.now(UTC)
    with SessionLocal() as session:
        _seed(session, now)
        session.commit()

    response = client.get(
        "/api/v1/customer-service/value-metrics"
        "?business_unit_id=bu_demo&days=30",
        headers=BUSINESS_MANAGER,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["business_unit_id"] == "bu_demo"
    assert payload["days"] == 30
    assert payload["drafts_total"] == 10
    assert payload["drafts_auto_accepted"] == 2
    assert payload["drafts_accepted"] == 3
    assert payload["drafts_edited_and_accepted"] == 2
    assert payload["drafts_rejected"] == 1
    assert payload["drafts_escalated"] == 1
    assert payload["drafts_pending"] == 1
    assert payload["drafts_reviewed"] == 7
    assert payload["adoption_rate"] == pytest.approx(5 / 7, abs=1e-4)
    assert payload["edit_rate"] == pytest.approx(0.4)
    assert payload["tickets_created"] == 3
    assert payload["conversations_created"] == 3
    assert payload["model_calls"] == 3
    assert payload["model_tokens"] == 350
    assert payload["estimated_cost"] == pytest.approx(0.035)
    assert payload["cost_per_conversation"] == pytest.approx(0.011667)
    assert payload["cost_per_adopted_draft"] == pytest.approx(0.007)
    assert payload["grounding_counts"] == {
        "GROUNDED": 7,
        "NO_KNOWLEDGE": 2,
        "UNVERIFIED": 1,
    }

    repeated = client.get(
        "/api/v1/customer-service/value-metrics"
        "?business_unit_id=bu_demo&days=30",
        headers=BUSINESS_MANAGER,
    )
    assert repeated.status_code == 200
    repeated_payload = repeated.json()
    window_keys = {"from_at", "to_at"}
    assert {
        key: value for key, value in repeated_payload.items() if key not in window_keys
    } == {key: value for key, value in payload.items() if key not in window_keys}
    assert repeated_payload["from_at"]
    assert repeated_payload["to_at"]

    weekly = client.get(
        "/api/v1/customer-service/value-metrics"
        "?business_unit_id=bu_demo&days=7",
        headers=BUSINESS_MANAGER,
    )
    weekly_payload = weekly.json()
    assert weekly.status_code == 200, weekly.text
    assert weekly_payload["drafts_total"] == 9
    assert weekly_payload["drafts_auto_accepted"] == 2
    assert weekly_payload["drafts_accepted"] == 2
    assert weekly_payload["drafts_reviewed"] == 6
    assert weekly_payload["adoption_rate"] == pytest.approx(4 / 6, abs=1e-4)
    assert weekly_payload["edit_rate"] == 0.5
    assert weekly_payload["tickets_created"] == 2
    assert weekly_payload["conversations_created"] == 3
    assert weekly_payload["model_calls"] == 2
    assert weekly_payload["model_tokens"] == 300
    assert weekly_payload["estimated_cost"] == pytest.approx(0.03)
    assert weekly_payload["cost_per_conversation"] == pytest.approx(0.01)
    assert weekly_payload["cost_per_adopted_draft"] == pytest.approx(0.0075)


def test_value_metrics_empty_window_returns_null_rates(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/v1/customer-service/value-metrics"
        "?business_unit_id=bu_demo&days=7",
        headers=BUSINESS_MANAGER,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["drafts_total"] == 0
    assert payload["adoption_rate"] is None
    assert payload["edit_rate"] is None
    assert payload["cost_per_conversation"] is None
    assert payload["cost_per_adopted_draft"] is None
    assert payload["grounding_counts"] == {}


def test_value_metrics_rejects_unknown_window_and_unauthorized_roles(
    client: TestClient,
) -> None:
    invalid = client.get(
        "/api/v1/customer-service/value-metrics"
        "?business_unit_id=bu_demo&days=0",
        headers=BUSINESS_MANAGER,
    )
    assert invalid.status_code == 422

    too_wide = client.get(
        "/api/v1/customer-service/value-metrics"
        "?business_unit_id=bu_demo&days=91",
        headers=BUSINESS_MANAGER,
    )
    assert too_wide.status_code == 422

    agent = client.get(
        "/api/v1/customer-service/value-metrics?business_unit_id=bu_demo",
        headers={"X-Actor-Id": "agent-value", "X-Actor-Role": "agent"},
    )
    assert agent.status_code == 403
    assert agent.json()["code"] == "FORBIDDEN"

    cross_unit = client.get(
        "/api/v1/customer-service/value-metrics?business_unit_id=bu_other",
        headers=BUSINESS_MANAGER,
    )
    assert cross_unit.status_code == 403
    assert cross_unit.json()["code"] == "BUSINESS_UNIT_ACCESS_DENIED"

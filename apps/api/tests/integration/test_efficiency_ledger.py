from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ticket_agent.customer_service.models import CustomerConversation
from ticket_agent.ecommerce.models import EcommerceListingTask, EcommerceProduct
from ticket_agent.efficiency.models import EfficiencyLedgerEntry
from ticket_agent.model_gateway.models import ModelCall
from ticket_agent.shared.db import system_session
from ticket_agent.tickets.models import Ticket

BUSINESS_MANAGER = {
    "X-Actor-Id": "efficiency-business-manager",
    "X-Actor-Role": "business_manager",
    "X-Business-Unit-Id": "bu_demo",
}
SUPERVISOR = {
    "X-Actor-Id": "efficiency-supervisor",
    "X-Actor-Role": "supervisor",
    "X-Business-Unit-Id": "bu_demo",
}
AGENT = {
    "X-Actor-Id": "efficiency-agent",
    "X-Actor-Role": "agent",
    "X-Business-Unit-Id": "bu_demo",
}
REQUESTER = {
    "X-Actor-Id": "efficiency-requester",
    "X-Actor-Role": "requester",
    "X-Business-Unit-Id": "bu_demo",
}

ASSUMPTIONS = {
    "currency": "CNY",
    "hourly_labor_cost": 60.0,
    "minutes_per_ticket": 15.0,
    "minutes_per_conversation": 8.0,
    "minutes_per_listing": 20.0,
}


def _now() -> datetime:
    return datetime.now(UTC)


def _ticket(
    session,
    *,
    business_unit_id: str = "bu_demo",
    status: str = "RESOLVED",
    workflow_state: str = "COMPLETED",
    updated_at: datetime | None = None,
) -> Ticket:
    moment = updated_at or _now()
    ticket = Ticket(
        business_unit_id=business_unit_id,
        source_system="efficiency_test",
        source_ticket_id=f"EFF-{uuid4()}",
        source_channel="web_form",
        idempotency_key=f"efficiency-{uuid4()}",
        request_hash="0" * 64,
        requester_ref="efficiency-customer",
        subject="效率账本测试工单",
        body="用于验证人时节省口径。",
        status=status,
        workflow_state=workflow_state,
        created_at=moment,
        updated_at=moment,
    )
    session.add(ticket)
    session.flush()
    return ticket


def _conversation(
    session,
    *,
    business_unit_id: str = "bu_demo",
    status: str = "RESOLVED",
    assigned_agent_id: str | None = None,
    current_ticket_id=None,
    updated_at: datetime | None = None,
) -> CustomerConversation:
    moment = updated_at or _now()
    conversation = CustomerConversation(
        business_unit_id=business_unit_id,
        requester_ref="efficiency-customer",
        status=status,
        assigned_agent_id=assigned_agent_id,
        current_ticket_id=current_ticket_id,
        created_at=moment,
        updated_at=moment,
    )
    session.add(conversation)
    session.flush()
    return conversation


def _listing(
    session,
    *,
    business_unit_id: str = "bu_demo",
    status: str = "PUBLISHED",
    updated_at: datetime | None = None,
) -> EcommerceListingTask:
    moment = updated_at or _now()
    product = EcommerceProduct(
        business_unit_id=business_unit_id,
        sku=f"EFF-SKU-{uuid4().hex[:10]}",
        name="效率账本测试商品",
        category="保温杯",
        price=129.0,
        attributes_json={},
        created_by="efficiency-test",
    )
    session.add(product)
    session.flush()
    task = EcommerceListingTask(
        product_id=product.id,
        business_unit_id=business_unit_id,
        channel="domestic_demo",
        sale_price=129.0,
        status=status,
        content_json={"title": "效率账本测试上架"},
        created_at=moment,
        updated_at=moment,
    )
    session.add(task)
    session.flush()
    return task


def _model_call(
    session,
    *,
    business_unit_id: str = "bu_demo",
    cost: float = 10.0,
    status: str = "SUCCEEDED",
    started_at: datetime | None = None,
) -> None:
    moment = started_at or _now()
    session.add(
        ModelCall(
            business_unit_id=business_unit_id,
            correlation_id=f"efficiency-{uuid4()}",
            purpose="classification",
            provider="local",
            model_name="local",
            status=status,
            input_tokens=100,
            output_tokens=0,
            total_tokens=100,
            estimated_cost=cost,
            latency_ms=5,
            started_at=moment,
            completed_at=moment,
        )
    )


def _rebuild(client: TestClient, headers: dict[str, str], days: int = 30):
    return client.post(
        "/api/v1/efficiency/rebuild?business_unit_id=bu_demo",
        headers=headers,
        json={"days": days},
    )


def test_empty_window_returns_zero_and_null_roi(client: TestClient) -> None:
    response = client.get(
        "/api/v1/efficiency/summary?business_unit_id=bu_demo&days=30",
        headers=BUSINESS_MANAGER,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["entries"] == 0
    assert body["human_minutes_saved"] == 0
    assert body["labor_cost_saved"] == 0
    assert body["model_cost"] == 0
    assert body["roi"] is None
    assert body["assumptions"]["persisted"] is False
    assert body["assumptions"]["hourly_labor_cost"] == 60.0
    assert body["basis"]


def test_rebuild_counts_three_sources_and_roi(client: TestClient) -> None:
    with system_session() as session:
        _ticket(session)
        _conversation(session)
        _listing(session)
        _model_call(session, cost=10.0)
        session.commit()

    rebuild = _rebuild(client, SUPERVISOR)
    assert rebuild.status_code == 200
    assert rebuild.json()["created"] == 3

    summary = client.get(
        "/api/v1/efficiency/summary?business_unit_id=bu_demo&days=30",
        headers=BUSINESS_MANAGER,
    ).json()
    assert summary["entries"] == 3
    assert summary["human_minutes_saved"] == 43.0
    assert summary["human_hours_saved"] == 0.72
    assert summary["labor_cost_saved"] == 43.0
    assert summary["model_cost"] == 10.0
    assert summary["roi"] == 4.3
    assert summary["net_saving"] == 33.0
    assert {item["source_type"] for item in summary["by_source"]} == {
        "TICKET_AUTO_RESOLVED",
        "CONVERSATION_RESOLVED",
        "ECOMMERCE_LISTING_COMPLETED",
    }
    assert summary["daily"][0]["entries"] == 3

    ledger = client.get(
        "/api/v1/efficiency/ledger?business_unit_id=bu_demo&days=30",
        headers=BUSINESS_MANAGER,
    ).json()
    assert ledger["total"] == 3
    assert len(ledger["items"]) == 3
    assert all(item["assumption_version"] == 0 for item in ledger["items"])


def test_rebuild_is_idempotent(client: TestClient) -> None:
    with system_session() as session:
        _ticket(session)
        _conversation(session)
        session.commit()

    first = _rebuild(client, SUPERVISOR).json()
    second = _rebuild(client, SUPERVISOR).json()
    third = _rebuild(client, SUPERVISOR).json()

    assert first["created"] == 2
    assert second["created"] == 0
    assert third["created"] == 0
    assert second["skipped_existing"] == 2
    with system_session() as session:
        assert session.query(EfficiencyLedgerEntry).count() == 2


def test_taken_over_ticket_and_assigned_conversation_are_excluded(
    client: TestClient,
) -> None:
    with system_session() as session:
        _ticket(session, status="RESOLVED", workflow_state="TAKEN_OVER")
        _conversation(session, assigned_agent_id="agent-1")
        session.commit()

    result = _rebuild(client, SUPERVISOR).json()
    assert result["created"] == 0
    assert result["skipped_existing"] == 0


def test_conversation_linked_to_counted_ticket_is_ineligible(
    client: TestClient,
) -> None:
    with system_session() as session:
        ticket = _ticket(session)
        _conversation(session, current_ticket_id=ticket.id)
        session.commit()

    result = _rebuild(client, SUPERVISOR).json()
    assert result["created"] == 1
    assert result["skipped_ineligible"] == 1


def test_conversation_does_not_double_count_ticket_from_earlier_window(
    client: TestClient,
) -> None:
    old = _now() - timedelta(days=40)
    with system_session() as session:
        ticket = _ticket(session, updated_at=old)
        session.add(
            EfficiencyLedgerEntry(
                business_unit_id="bu_demo",
                source_type="TICKET_AUTO_RESOLVED",
                source_id=ticket.id,
                occurred_at=old,
                human_minutes_saved=15,
                labor_cost_saved=15,
                currency="CNY",
                assumption_snapshot={"assumption_version": 0},
            )
        )
        _conversation(session, current_ticket_id=ticket.id)
        session.commit()

    result = _rebuild(client, SUPERVISOR, days=30).json()
    assert result["created"] == 0
    assert result["skipped_ineligible"] == 1


def test_assumption_snapshot_is_frozen(client: TestClient) -> None:
    with system_session() as session:
        _ticket(session)
        session.commit()

    assert _rebuild(client, SUPERVISOR).json()["created"] == 1

    update = client.put(
        "/api/v1/efficiency/assumptions?business_unit_id=bu_demo",
        headers=SUPERVISOR,
        json={**ASSUMPTIONS, "hourly_labor_cost": 120.0},
    )
    assert update.status_code == 200
    assert update.json()["version"] == 1

    assert _rebuild(client, SUPERVISOR).json()["created"] == 0

    summary = client.get(
        "/api/v1/efficiency/summary?business_unit_id=bu_demo&days=30",
        headers=BUSINESS_MANAGER,
    ).json()
    assert summary["labor_cost_saved"] == 15.0
    ledger = client.get(
        "/api/v1/efficiency/ledger?business_unit_id=bu_demo&days=30",
        headers=BUSINESS_MANAGER,
    ).json()
    assert ledger["items"][0]["assumption_version"] == 0

    with system_session() as session:
        _ticket(session)
        session.commit()
    assert _rebuild(client, SUPERVISOR).json()["created"] == 1
    summary = client.get(
        "/api/v1/efficiency/summary?business_unit_id=bu_demo&days=30",
        headers=BUSINESS_MANAGER,
    ).json()
    # 15 minutes at the old 60/h plus 15 minutes at the new 120/h.
    assert summary["labor_cost_saved"] == 45.0
    ledger = client.get(
        "/api/v1/efficiency/ledger?business_unit_id=bu_demo&days=30",
        headers=BUSINESS_MANAGER,
    ).json()
    assert {item["assumption_version"] for item in ledger["items"]} == {0, 1}


def test_permissions_and_tenant_isolation(client: TestClient) -> None:
    assert (
        client.get(
            "/api/v1/efficiency/summary?business_unit_id=bu_demo",
            headers=AGENT,
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/api/v1/efficiency/summary?business_unit_id=bu_demo",
            headers=REQUESTER,
        ).status_code
        == 403
    )
    assert (
        client.put(
            "/api/v1/efficiency/assumptions?business_unit_id=bu_demo",
            headers=AGENT,
            json=ASSUMPTIONS,
        ).status_code
        == 403
    )
    assert _rebuild(client, AGENT).status_code == 403
    assert (
        client.get(
            "/api/v1/efficiency/summary?business_unit_id=bu_other",
            headers=SUPERVISOR,
        ).status_code
        == 403
    )

    with system_session() as session:
        _ticket(session, business_unit_id="bu_other")
        session.commit()

    assert _rebuild(client, SUPERVISOR).json()["created"] == 0
    assert (
        client.get(
            "/api/v1/efficiency/summary?business_unit_id=bu_demo",
            headers=BUSINESS_MANAGER,
        ).json()["entries"]
        == 0
    )


def test_assumption_updates_are_versioned_and_validated(
    client: TestClient,
) -> None:
    initial = client.get(
        "/api/v1/efficiency/assumptions?business_unit_id=bu_demo",
        headers=BUSINESS_MANAGER,
    ).json()
    assert initial["persisted"] is False
    assert initial["version"] == 0

    first = client.put(
        "/api/v1/efficiency/assumptions?business_unit_id=bu_demo",
        headers=SUPERVISOR,
        json=ASSUMPTIONS,
    )
    assert first.status_code == 200
    assert first.json()["persisted"] is True
    assert first.json()["version"] == 1

    second = client.put(
        "/api/v1/efficiency/assumptions?business_unit_id=bu_demo",
        headers=SUPERVISOR,
        json={**ASSUMPTIONS, "minutes_per_ticket": 5.0},
    )
    assert second.json()["version"] == 2

    negative_cost = client.put(
        "/api/v1/efficiency/assumptions?business_unit_id=bu_demo",
        headers=SUPERVISOR,
        json={**ASSUMPTIONS, "hourly_labor_cost": -1},
    )
    assert negative_cost.status_code == 422
    negative_minutes = client.put(
        "/api/v1/efficiency/assumptions?business_unit_id=bu_demo",
        headers=SUPERVISOR,
        json={**ASSUMPTIONS, "minutes_per_conversation": -1},
    )
    assert negative_minutes.status_code == 422


def test_invalid_window_is_rejected(client: TestClient) -> None:
    for days in (0, 366, -3):
        response = client.get(
            f"/api/v1/efficiency/summary?business_unit_id=bu_demo&days={days}",
            headers=BUSINESS_MANAGER,
        )
        assert response.status_code == 422
        assert response.json()["code"] == "INVALID_WINDOW"

    rebuild = _rebuild(client, SUPERVISOR, days=0)
    assert rebuild.status_code == 422
    assert rebuild.json()["code"] == "INVALID_WINDOW"


def test_window_excludes_old_objects_and_backfills_when_widened(
    client: TestClient,
) -> None:
    old = _now() - timedelta(days=20)
    with system_session() as session:
        _ticket(session, updated_at=old)
        session.commit()

    narrow = _rebuild(client, SUPERVISOR, days=7).json()
    assert narrow["created"] == 0

    wide = _rebuild(client, SUPERVISOR, days=30).json()
    assert wide["created"] == 1


def test_failed_model_calls_do_not_inflate_cost(client: TestClient) -> None:
    with system_session() as session:
        _ticket(session)
        _model_call(session, cost=10.0, status="SUCCEEDED")
        _model_call(session, cost=999.0, status="FAILED")
        session.commit()

    _rebuild(client, SUPERVISOR)
    summary = client.get(
        "/api/v1/efficiency/summary?business_unit_id=bu_demo&days=30",
        headers=BUSINESS_MANAGER,
    ).json()
    assert summary["model_cost"] == 10.0
    assert summary["model_calls"] == 1


@pytest.mark.parametrize("status", ["SUCCEEDED", "PUBLISHED"])
def test_listing_statuses_are_counted(client: TestClient, status: str) -> None:
    with system_session() as session:
        _listing(session, status=status)
        session.commit()

    assert _rebuild(client, SUPERVISOR).json()["created"] == 1

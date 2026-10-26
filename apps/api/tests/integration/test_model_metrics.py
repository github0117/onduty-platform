from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from ticket_agent.model_gateway.models import ModelCall
from ticket_agent.shared.db import SessionLocal


def test_model_metrics_endpoint(client: TestClient) -> None:
    with SessionLocal() as session:
        session.add(
            ModelCall(
                employee_id=uuid4(),
                business_unit_id="bu_demo",
                correlation_id="model-metrics",
                purpose="classification",
                provider="openai_compatible",
                model_name="classifier",
                status="SUCCEEDED",
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
                estimated_cost=0.02,
                latency_ms=120,
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
        )
        session.commit()

    response = client.get(
        "/api/v1/metrics/models",
        headers={"X-Actor-Id": "auditor-model", "X-Actor-Role": "auditor"},
    )

    assert response.status_code == 200
    assert response.json()["calls"] == 1
    assert response.json()["total_tokens"] == 150
    assert response.json()["estimated_cost"] == 0.02
    assert response.json()["by_purpose"][0]["purpose"] == "classification"

    filtered = client.get(
        "/api/v1/metrics/models?business_unit_id=bu_other",
        headers={"X-Actor-Id": "auditor-model", "X-Actor-Role": "auditor"},
    )

    assert filtered.status_code == 403
    assert filtered.json()["code"] == "BUSINESS_UNIT_ACCESS_DENIED"


def test_model_budget_endpoint_reports_current_period_usage(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/v1/digital-employees",
        headers={"X-Actor-Id": "admin-budget", "X-Actor-Role": "admin"},
        json={
            "employee_key": "budget_employee",
            "name": "预算测试员工",
            "version": "1.0.0",
            "scenario_type": "customer_service_ticket",
            "workflow_key": "customer_service_ticket_v1",
            "business_unit_id": "bu_demo",
            "service_identity": "digital_employee.budget",
            "handoff_queue": "BUDGET_QUEUE",
            "knowledge_policy": {},
            "model_profile": {"budgets": {"daily_calls": 1, "weekly_cost": 2}},
            "tool_allowlist": ["ticket.read"],
        },
    )
    assert created.status_code == 201, created.text
    employee_id = created.json()["id"]
    now = datetime.now(UTC)
    with SessionLocal() as session:
        session.add(
            ModelCall(
                employee_id=UUID(employee_id),
                business_unit_id="bu_demo",
                correlation_id="budget-endpoint",
                purpose="classification",
                provider="openai_compatible",
                model_name="classifier",
                status="SUCCEEDED",
                input_tokens=10,
                output_tokens=5,
                total_tokens=15,
                estimated_cost=0.01,
                latency_ms=100,
                started_at=now,
                completed_at=now,
            )
        )
        session.commit()

    response = client.get(
        f"/api/v1/metrics/models/budget?employee_id={employee_id}",
        headers={"X-Actor-Id": "auditor-budget", "X-Actor-Role": "auditor"},
    )

    assert response.status_code == 200
    assert response.json()["exceeded"] is True
    daily = next(
        period for period in response.json()["periods"] if period["period"] == "daily"
    )
    assert "DAILY_CALLS_EXCEEDED" in daily["alerts"]


def test_runtime_config_endpoint_hides_secrets(client: TestClient) -> None:
    response = client.get(
        "/api/v1/system/runtime",
        headers={"X-Actor-Id": "auditor-runtime", "X-Actor-Role": "auditor"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["model_provider"] == "local"
    assert payload["embedding_provider"] == "local"
    assert "model_api_key" not in payload
    assert "embedding_api_key" not in payload
    assert isinstance(payload["model_api_key_configured"], bool)


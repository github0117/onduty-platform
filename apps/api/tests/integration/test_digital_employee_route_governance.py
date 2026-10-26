from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.shared.db import SessionLocal

ADMIN = {"X-Actor-Id": "route-governance-admin", "X-Actor-Role": "admin"}
AGENT = {"X-Actor-Id": "route-governance-agent", "X-Actor-Role": "agent"}
KNOWLEDGE_OPERATOR = {
    "X-Actor-Id": "route-governance-operator",
    "X-Actor-Role": "knowledge_operator",
}


def _create_employee(
    client: TestClient,
    *,
    template_code: str,
    name: str,
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/digital-employees/from-template",
        headers=ADMIN,
        json={
            "name": name,
            "template_code": template_code,
            "business_unit_id": "bu_demo",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _set_route_rule(
    client: TestClient,
    employee_id: str,
    *,
    intents: list[str],
    priority: int,
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


def _create_entry(
    client: TestClient,
    *,
    code: str,
    default_employee_id: str,
    employee_ids: list[str],
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/business-service-entries",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "code": code,
            "name": "企业服务台入口",
            "description": "路由评测测试入口",
            "domain": "enterprise_service",
            "channel": "enterprise_service",
            "default_employee_id": default_employee_id,
            "fallback_employee_id": default_employee_id,
            "human_queue_id": "ENTERPRISE_SERVICE_DESK",
            "employees": [
                {
                    "employee_id": employee_id,
                    "role_type": (
                        "PRIMARY" if employee_id == default_employee_id else "SPECIALIST"
                    ),
                    "priority": index * 10,
                }
                for index, employee_id in enumerate(employee_ids, start=1)
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _add_case(
    client: TestClient,
    *,
    entry_id: str,
    employee_id: str,
    question: str,
    headers: dict[str, str] = ADMIN,
) -> Any:
    return client.post(
        "/api/v1/digital-employee-route-evaluation-cases",
        headers=headers,
        params={"business_unit_id": "bu_demo"},
        json={
            "service_entry_id": entry_id,
            "expected_employee_id": employee_id,
            "question": question,
            "notes": "路由回归",
        },
    )


def _append_manifest_terms(
    employee_id: str,
    *terms: str,
) -> None:
    with SessionLocal() as session:
        employee = session.get(DigitalEmployee, UUID(employee_id))
        assert employee is not None
        manifest = dict(employee.manifest_json)
        manifest["intents"] = [
            *manifest.get("intents", []),
            *terms,
        ]
        employee.manifest_json = manifest
        session.commit()


def test_route_evaluation_reports_accuracy_and_suppressed_intents(
    client: TestClient,
) -> None:
    enterprise = _create_employee(
        client,
        template_code="enterprise_service_desk",
        name="企业服务台",
    )
    hr = _create_employee(
        client,
        template_code="hr_onboarding",
        name="HR 入职专员",
    )
    _set_route_rule(
        client,
        enterprise["id"],
        intents=["会议室", "报销", "账号", "VPN"],
        priority=50,
    )
    _set_route_rule(
        client,
        hr["id"],
        intents=["入职", "请假", "年假"],
        priority=10,
    )
    entry = _create_entry(
        client,
        code="route_governance_entry",
        default_employee_id=enterprise["id"],
        employee_ids=[enterprise["id"], hr["id"]],
    )
    # Simulate a stale manifest that still carries HR terms inherited from
    # the old template. Explicit ownership should suppress them at runtime.
    _append_manifest_terms(enterprise["id"], "请假", "年假", "入职")

    for employee_id, question in (
        (hr["id"], "请假需要提前几天申请？"),
        (enterprise["id"], "会议室怎么预订？"),
    ):
        created = _add_case(
            client,
            entry_id=entry["id"],
            employee_id=employee_id,
            question=question,
        )
        assert created.status_code == 201, created.text

    response = client.post(
        "/api/v1/digital-employee-route-evaluation-runs",
        headers=KNOWLEDGE_OPERATOR,
        params={"business_unit_id": "bu_demo"},
        json={"service_entry_id": entry["id"]},
    )
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["total"] == 2
    assert run["passed"] == 2
    assert run["failed"] == 0
    assert run["accuracy"] == 1.0
    assert run["created_by"] == KNOWLEDGE_OPERATOR["X-Actor-Id"]

    leave_result = next(item for item in run["results"] if item["question"].startswith("请假"))
    assert leave_result["predicted_employee_id"] == hr["id"]
    assert leave_result["matched"] is True
    enterprise_candidate = next(
        item for item in leave_result["candidates"] if item["employee_id"] == enterprise["id"]
    )
    assert "请假" in enterprise_candidate["suppressed_intents"]
    assert "请假" not in enterprise_candidate["inherited_intents"]
    assert "请假" not in enterprise_candidate["matched_intents"]

    listed = client.get(
        "/api/v1/digital-employee-route-evaluation-runs",
        headers=AGENT,
        params={
            "business_unit_id": "bu_demo",
            "service_entry_id": entry["id"],
        },
    )
    assert listed.status_code == 200, listed.text
    payload = listed.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == run["id"]

    decisions = client.get(
        "/api/v1/digital-employee-route-decisions",
        headers=AGENT,
        params={"business_unit_id": "bu_demo"},
    )
    assert decisions.status_code == 200, decisions.text
    assert decisions.json()["total"] == 0


def test_route_evaluation_case_crud_and_permissions(
    client: TestClient,
) -> None:
    enterprise = _create_employee(
        client,
        template_code="enterprise_service_desk",
        name="服务台",
    )
    hr = _create_employee(
        client,
        template_code="hr_onboarding",
        name="HR",
    )
    _set_route_rule(
        client,
        enterprise["id"],
        intents=["会议室"],
        priority=50,
    )
    entry = _create_entry(
        client,
        code="route_evaluation_crud",
        default_employee_id=enterprise["id"],
        employee_ids=[enterprise["id"]],
    )
    denied = _add_case(
        client,
        entry_id=entry["id"],
        employee_id=enterprise["id"],
        question="会议室怎么预订？",
        headers=AGENT,
    )
    assert denied.status_code == 403

    created = _add_case(
        client,
        entry_id=entry["id"],
        employee_id=enterprise["id"],
        question="会议室怎么预订？",
    )
    assert created.status_code == 201, created.text
    case = created.json()
    assert case["expected_employee_name"] == "服务台"
    duplicate = _add_case(
        client,
        entry_id=entry["id"],
        employee_id=enterprise["id"],
        question="会议室怎么预订？",
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "ROUTE_EVALUATION_CASE_EXISTS"

    # An expected employee outside the entry pool is rejected.
    outside = client.patch(
        f"/api/v1/digital-employee-route-evaluation-cases/{case['id']}",
        headers=ADMIN,
        json={"expected_employee_id": hr["id"]},
    )
    assert outside.status_code == 409
    assert outside.json()["code"] == "ROUTE_EVALUATION_EMPLOYEE_NOT_IN_ENTRY"

    disabled = client.patch(
        f"/api/v1/digital-employee-route-evaluation-cases/{case['id']}",
        headers=KNOWLEDGE_OPERATOR,
        json={"enabled": False},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["enabled"] is False

    no_cases = client.post(
        "/api/v1/digital-employee-route-evaluation-runs",
        headers=ADMIN,
        params={"business_unit_id": "bu_demo"},
        json={"service_entry_id": entry["id"]},
    )
    assert no_cases.status_code == 409
    assert no_cases.json()["code"] == "ROUTE_EVALUATION_NO_CASES"

    agent_run = client.post(
        "/api/v1/digital-employee-route-evaluation-runs",
        headers=AGENT,
        params={"business_unit_id": "bu_demo"},
        json={"service_entry_id": entry["id"]},
    )
    assert agent_run.status_code == 403

    deleted = client.delete(
        f"/api/v1/digital-employee-route-evaluation-cases/{case['id']}",
        headers=ADMIN,
    )
    assert deleted.status_code == 204, deleted.text
    remaining = client.get(
        "/api/v1/digital-employee-route-evaluation-cases",
        headers=AGENT,
        params={
            "business_unit_id": "bu_demo",
            "service_entry_id": entry["id"],
        },
    )
    assert remaining.status_code == 200, remaining.text
    assert remaining.json() == []


def test_intent_conflict_endpoint_reports_conflicts_and_suppressions(
    client: TestClient,
) -> None:
    enterprise = _create_employee(
        client,
        template_code="enterprise_service_desk",
        name="企业服务台",
    )
    hr = _create_employee(
        client,
        template_code="hr_onboarding",
        name="HR 入职专员",
    )
    finance = _create_employee(
        client,
        template_code="enterprise_service_desk",
        name="财务共享服务",
    )
    _set_route_rule(
        client,
        enterprise["id"],
        intents=["报销", "会议室"],
        priority=50,
    )
    _set_route_rule(
        client,
        hr["id"],
        intents=["入职", "请假"],
        priority=10,
    )
    _set_route_rule(
        client,
        finance["id"],
        intents=["报销", "发票"],
        priority=20,
    )
    entry = _create_entry(
        client,
        code="route_intent_conflicts",
        default_employee_id=enterprise["id"],
        employee_ids=[enterprise["id"], hr["id"], finance["id"]],
    )
    _append_manifest_terms(enterprise["id"], "入职", "请假")

    response = client.get(
        "/api/v1/digital-employee-route-intent-conflicts",
        headers=AGENT,
        params={"business_unit_id": "bu_demo"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["business_unit_id"] == "bu_demo"
    assert payload["active_employee_count"] >= 3

    conflict = next(item for item in payload["conflicts"] if item["term"] == "报销")
    assert conflict["source"] == "EXPLICIT"
    assert set(conflict["employee_ids"]) == {
        enterprise["id"],
        finance["id"],
    }
    assert entry["id"] in conflict["entry_ids"]

    suppression = next(item for item in payload["suppressed"] if item["term"] == "请假")
    assert suppression["affected_employee_ids"] == [enterprise["id"]]
    assert suppression["owner_employee_ids"] == [hr["id"]]
    assert entry["id"] in suppression["entry_ids"]

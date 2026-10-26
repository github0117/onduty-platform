from fastapi.testclient import TestClient

ADMIN = {"X-Actor-Id": "skill-admin", "X-Actor-Role": "admin"}
AGENT = {"X-Actor-Id": "skill-agent", "X-Actor-Role": "agent"}


def test_skill_crud_and_employee_binding(client: TestClient) -> None:
    defaults = client.get(
        "/api/v1/skills?business_unit_id=bu_demo",
        headers=AGENT,
    )
    assert defaults.status_code == 200
    assert {item["code"] for item in defaults.json()} == {
        "ecommerce-presales",
        "ecommerce-aftersales",
        "logistics-inquiry",
        "hr-onboarding",
        "customer-service-supervisor",
    }

    created = client.post(
        "/api/v1/skills",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "code": "warranty-check",
            "name": "保修资格核对",
            "description": "核对商品保修时间和凭证。",
            "instructions": "先查保修政策，再要求用户提供订单号和凭证。",
            "triggers": ["保修", "质保"],
            "tools": ["knowledge.search"],
        },
    )
    assert created.status_code == 201, created.text
    skill_id = created.json()["id"]
    updated = client.patch(
        f"/api/v1/skills/{skill_id}",
        headers=ADMIN,
        json={"triggers": ["保修", "质保", "坏了"]},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert "坏了" in updated.json()["triggers"]

    employee = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json={
            "employee_key": "skill_test_employee",
            "name": "Skill 测试客服",
            "version": "1.0.0",
            "scenario_type": "customer_service_ticket",
            "workflow_key": "customer_service_ticket_v1",
            "business_unit_id": "bu_demo",
            "service_identity": "digital_employee.skill_test",
            "handoff_queue": "MANUAL_TRIAGE",
            "tool_allowlist": ["ticket.read", "knowledge.search", "draft.create"],
        },
    )
    assert employee.status_code == 201, employee.text
    bound = client.put(
        f"/api/v1/digital-employees/{employee.json()['id']}/skills",
        headers=ADMIN,
        json={
            "bindings": [
                {
                    "skill_id": skill_id,
                    "enabled": True,
                    "priority": 10,
                }
            ]
        },
    )
    assert bound.status_code == 200, bound.text
    assert bound.json()[0]["skill_code"] == "warranty-check"

    listed = client.get(
        f"/api/v1/digital-employees/{employee.json()['id']}/skills",
        headers=AGENT,
    )
    assert listed.status_code == 200
    assert listed.json()[0]["skill_name"] == "保修资格核对"

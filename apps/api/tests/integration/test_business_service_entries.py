from fastapi.testclient import TestClient

ADMIN = {"X-Actor-Id": "business-entry-admin", "X-Actor-Role": "admin"}
AGENT = {"X-Actor-Id": "business-entry-agent", "X-Actor-Role": "agent"}
KNOWLEDGE_OPERATOR = {
    "X-Actor-Id": "business-entry-knowledge-operator",
    "X-Actor-Role": "knowledge_operator",
}
BUSINESS_MANAGER = {
    "X-Actor-Id": "business-entry-manager",
    "X-Actor-Role": "business_manager",
}


def _create_employee(
    client: TestClient,
    *,
    template_code: str,
    name: str,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/digital-employees/from-template",
        headers=ADMIN,
        json={
            "name": name,
            "template_code": template_code,
            "business_unit_id": "bu_demo",
            "knowledge_space_ids": [],
            "skill_ids": [],
            "mcp_connector_ids": [],
            "model_profile": {},
            "change_note": "business entry test",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_business_entry_binds_multiple_employees(
    client: TestClient,
) -> None:
    presales = _create_employee(
        client,
        template_code="ecommerce_presales",
        name="商品咨询数字员工",
    )
    logistics = _create_employee(
        client,
        template_code="ecommerce_logistics",
        name="物流查询数字员工",
    )
    created = client.post(
        "/api/v1/business-service-entries",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "code": "ecommerce_customer_service",
            "name": "国内电商客服入口",
            "description": "承接商品、物流和售后问题",
            "domain": "ecommerce",
            "channel": "web_form",
            "default_employee_id": presales["id"],
            "fallback_employee_id": logistics["id"],
            "human_queue_id": "ECOMMERCE_SERVICE_HUMAN",
            "employees": [
                {
                    "employee_id": presales["id"],
                    "role_type": "PRIMARY",
                    "priority": 10,
                },
                {
                    "employee_id": logistics["id"],
                    "role_type": "SPECIALIST",
                    "priority": 20,
                },
            ],
        },
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["code"] == "ecommerce_customer_service"
    assert {
        item["employee_id"] for item in payload["employees"]
    } == {presales["id"], logistics["id"]}

    listed = client.get(
        "/api/v1/business-service-entries?business_unit_id=bu_demo",
        headers=AGENT,
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["employees"][0]["employee_name"] in {
        "商品咨询数字员工",
        "物流查询数字员工",
    }

    conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "service_entry_id": payload["id"],
            "requester_ref": "business-entry-buyer",
        },
    )
    assert conversation.status_code == 201, conversation.text
    assert conversation.json()["service_entry_id"] == payload["id"]
    message = client.post(
        (
            "/api/v1/customer-service/conversations/"
            f"{conversation.json()['id']}/messages"
        ),
        headers=AGENT,
        json={"content": "我的快递到哪了，帮我查一下物流"},
    )
    assert message.status_code == 202, message.text
    ticket = client.get(
        f"/api/v1/tickets/{message.json()['current_ticket_id']}",
        headers=AGENT,
    )
    assert ticket.status_code == 200, ticket.text
    assert ticket.json()["employee"]["id"] == logistics["id"]


def test_business_entry_rejects_duplicate_employee_binding(
    client: TestClient,
) -> None:
    employee = _create_employee(
        client,
        template_code="ecommerce_presales",
        name="重复绑定测试员工",
    )
    response = client.post(
        "/api/v1/business-service-entries",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "code": "duplicate_employee_entry",
            "name": "重复绑定入口",
            "domain": "ecommerce",
            "channel": "web_form",
            "employees": [
                {"employee_id": employee["id"]},
                {"employee_id": employee["id"]},
            ],
        },
    )

    assert response.status_code == 422
    assert (
        response.json()["code"]
        == "BUSINESS_SERVICE_ENTRY_DUPLICATE_EMPLOYEE"
    )


def test_business_entry_read_and_write_roles_stay_separate(
    client: TestClient,
) -> None:
    employee = _create_employee(
        client,
        template_code="ecommerce_presales",
        name="权限矩阵测试员工",
    )
    created = client.post(
        "/api/v1/business-service-entries",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "code": "business_entry_role_matrix",
            "name": "权限矩阵测试入口",
            "domain": "ecommerce",
            "channel": "web_form",
            "default_employee_id": employee["id"],
            "fallback_employee_id": employee["id"],
            "employees": [{"employee_id": employee["id"]}],
        },
    )
    assert created.status_code == 201, created.text
    entry = created.json()

    for headers in (KNOWLEDGE_OPERATOR, BUSINESS_MANAGER):
        listed = client.get(
            "/api/v1/business-service-entries?business_unit_id=bu_demo",
            headers=headers,
        )
        assert listed.status_code == 200, listed.text
        assert any(item["id"] == entry["id"] for item in listed.json())

    denied = client.patch(
        f"/api/v1/business-service-entries/{entry['id']}",
        headers=BUSINESS_MANAGER,
        json={"expected_version": entry["version"], "name": "越权修改"},
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "FORBIDDEN"

from fastapi.testclient import TestClient


def _payload(
    *,
    source_id: str,
    requester_ref: str,
) -> dict[str, object]:
    return {
        "business_unit_id": "bu_demo",
        "source": {
            "system": "demo_helpdesk",
            "channel": "web_form",
            "external_ticket_id": source_id,
        },
        "requester": {
            "external_ref": requester_ref,
            "customer_tier": "standard",
        },
        "subject": "如何配置企业通知",
        "body": "请问管理员如何为团队配置消息通知？",
        "locale": "zh-CN",
        "attachments": [],
        "metadata": {},
    }


def test_requester_only_views_own_ticket(client: TestClient) -> None:
    created = client.post(
        "/api/v1/tickets",
        json=_payload(source_id="AUTH-001", requester_ref="customer-owner"),
        headers={
            "Idempotency-Key": "auth:AUTH-001",
            "X-Actor-Id": "agent-1",
            "X-Actor-Role": "agent",
        },
    )
    ticket_id = created.json()["id"]

    own = client.get(
        f"/api/v1/tickets/{ticket_id}",
        headers={"X-Actor-Id": "customer-owner", "X-Actor-Role": "requester"},
    )
    other = client.get(
        f"/api/v1/tickets/{ticket_id}",
        headers={"X-Actor-Id": "customer-other", "X-Actor-Role": "requester"},
    )

    assert own.status_code == 200
    assert other.status_code == 403
    assert other.json()["code"] == "FORBIDDEN"


def test_requester_list_is_filtered_to_own_tickets(client: TestClient) -> None:
    for index, requester in enumerate(("customer-a", "customer-b"), start=1):
        client.post(
            "/api/v1/tickets",
            json=_payload(source_id=f"AUTH-LIST-{index}", requester_ref=requester),
            headers={
                "Idempotency-Key": f"auth:AUTH-LIST-{index}",
                "X-Actor-Id": "agent-1",
                "X-Actor-Role": "agent",
            },
        )

    response = client.get(
        "/api/v1/tickets?business_unit_id=bu_demo",
        headers={"X-Actor-Id": "customer-a", "X-Actor-Role": "requester"},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["subject"] == "如何配置企业通知"


def test_auditor_can_read_but_cannot_take_over(client: TestClient) -> None:
    created = client.post(
        "/api/v1/tickets",
        json=_payload(source_id="AUTH-002", requester_ref="customer-owner"),
        headers={
            "Idempotency-Key": "auth:AUTH-002",
            "X-Actor-Id": "agent-1",
            "X-Actor-Role": "agent",
        },
    )
    ticket_id = created.json()["id"]
    detail = client.get(
        f"/api/v1/tickets/{ticket_id}",
        headers={"X-Actor-Id": "auditor-1", "X-Actor-Role": "auditor"},
    )
    takeover = client.post(
        f"/api/v1/tickets/{ticket_id}/takeover",
        json={"expected_version": detail.json()["version"], "reason_code": "AUDIT"},
        headers={"X-Actor-Id": "auditor-1", "X-Actor-Role": "auditor"},
    )

    assert detail.status_code == 200
    assert takeover.status_code == 403


def test_business_manager_can_read_but_cannot_take_over(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/v1/tickets",
        json=_payload(source_id="AUTH-BM-001", requester_ref="customer-owner"),
        headers={
            "Idempotency-Key": "auth:AUTH-BM-001",
            "X-Actor-Id": "agent-1",
            "X-Actor-Role": "agent",
        },
    )
    ticket_id = created.json()["id"]
    headers = {
        "X-Actor-Id": "business-manager-1",
        "X-Actor-Role": "business_manager",
    }
    detail = client.get(f"/api/v1/tickets/{ticket_id}", headers=headers)
    takeover = client.post(
        f"/api/v1/tickets/{ticket_id}/takeover",
        json={"expected_version": detail.json()["version"], "reason_code": "AUDIT"},
        headers=headers,
    )

    assert detail.status_code == 200
    assert takeover.status_code == 403


def test_business_manager_can_read_employee_catalog(client: TestClient) -> None:
    headers = {
        "X-Actor-Id": "business-manager-1",
        "X-Actor-Role": "business_manager",
        "X-Business-Unit-Id": "bu_demo",
    }

    employees = client.get(
        "/api/v1/digital-employees?business_unit_id=bu_demo",
        headers=headers,
    )
    templates = client.get(
        "/api/v1/digital-employee-templates?business_unit_id=bu_demo",
        headers=headers,
    )

    assert employees.status_code == 200
    assert templates.status_code == 200
    assert len(templates.json()) >= 6


def test_knowledge_operator_can_manage_knowledge_but_not_tickets(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/v1/tickets",
        json=_payload(source_id="AUTH-KO-001", requester_ref="customer-owner"),
        headers={
            "Idempotency-Key": "auth:AUTH-KO-001",
            "X-Actor-Id": "agent-1",
            "X-Actor-Role": "agent",
        },
    )
    ticket_id = created.json()["id"]
    headers = {
        "X-Actor-Id": "knowledge-operator-1",
        "X-Actor-Role": "knowledge_operator",
        "X-Business-Unit-Id": "bu_demo",
    }

    documents = client.get(
        "/api/v1/knowledge-documents?business_unit_id=bu_demo",
        headers=headers,
    )
    spaces = client.get(
        "/api/v1/knowledge-spaces?business_unit_id=bu_demo",
        headers=headers,
    )
    cases = client.get(
        "/api/v1/knowledge/evaluation-cases?business_unit_id=bu_demo",
        headers=headers,
    )
    takeover = client.post(
        f"/api/v1/tickets/{ticket_id}/takeover",
        json={"expected_version": 1, "reason_code": "KNOWLEDGE"},
        headers=headers,
    )

    assert documents.status_code == 200
    assert spaces.status_code == 200
    assert cases.status_code == 200
    assert takeover.status_code == 403


def _role_headers(role: str) -> dict[str, str]:
    return {
        "X-Actor-Id": f"{role}-1",
        "X-Actor-Role": role,
        "X-Business-Unit-Id": "bu_demo",
    }


def test_ecommerce_read_does_not_grant_operate(client: TestClient) -> None:
    for role in ("agent", "business_manager", "knowledge_operator"):
        listing = client.get(
            "/api/v1/ecommerce/categories?business_unit_id=bu_demo",
            headers=_role_headers(role),
        )
        assert listing.status_code == 200, (role, listing.text)

    for role in ("agent", "business_manager", "knowledge_operator"):
        operate = client.post(
            "/api/v1/ecommerce/channels/pinduoduo/test",
            headers=_role_headers(role),
        )
        assert operate.status_code == 403, (role, operate.text)

    supervisor = client.post(
        "/api/v1/ecommerce/channels/pinduoduo/test",
        headers=_role_headers("supervisor"),
    )
    assert supervisor.status_code == 200

    requester = client.get(
        "/api/v1/ecommerce/categories?business_unit_id=bu_demo",
        headers=_role_headers("requester"),
    )
    assert requester.status_code == 403


def test_mcp_oversight_read_is_separate_from_decide(client: TestClient) -> None:
    for role in ("supervisor", "business_manager", "auditor"):
        approvals = client.get(
            "/api/v1/mcp/tool-approvals?business_unit_id=bu_demo",
            headers=_role_headers(role),
        )
        incidents = client.get(
            "/api/v1/mcp/action-incidents?business_unit_id=bu_demo",
            headers=_role_headers(role),
        )
        assert approvals.status_code == 200, (role, approvals.text)
        assert incidents.status_code == 200, (role, incidents.text)

    agent = client.get(
        "/api/v1/mcp/tool-approvals?business_unit_id=bu_demo",
        headers=_role_headers("agent"),
    )
    assert agent.status_code == 403


def test_customer_service_metrics_require_service_admin(
    client: TestClient,
) -> None:
    supervisor = client.get(
        "/api/v1/customer-service/metrics?business_unit_id=bu_demo",
        headers=_role_headers("supervisor"),
    )
    assert supervisor.status_code == 200

    for role in ("agent", "auditor", "business_manager"):
        denied = client.get(
            "/api/v1/customer-service/metrics?business_unit_id=bu_demo",
            headers=_role_headers(role),
        )
        assert denied.status_code == 403, (role, denied.text)


def test_requester_cannot_create_ticket_for_another_customer(client: TestClient) -> None:
    response = client.post(
        "/api/v1/tickets",
        json=_payload(source_id="AUTH-003", requester_ref="customer-other"),
        headers={
            "Idempotency-Key": "auth:AUTH-003",
            "X-Actor-Id": "customer-self",
            "X-Actor-Role": "requester",
        },
    )

    assert response.status_code == 403


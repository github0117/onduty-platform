import pytest
from fastapi.testclient import TestClient

from ticket_agent.digital_employees import service as employee_service
from ticket_agent.shared.settings import Settings

ADMIN = {"X-Actor-Id": "admin-1", "X-Actor-Role": "admin"}
AGENT = {"X-Actor-Id": "agent-1", "X-Actor-Role": "agent"}


def _employee_payload(key: str = "secondary_ticket_employee") -> dict[str, object]:
    return {
        "employee_key": key,
        "name": "二级客服数字员工",
        "version": "1.0.0",
        "scenario_type": "customer_service_ticket",
        "workflow_key": "customer_service_ticket_v1",
        "business_unit_id": "bu_demo",
        "service_identity": f"digital_employee.{key}",
        "handoff_queue": "SECONDARY_HUMAN_QUEUE",
        "knowledge_policy": {"default_scope": {"products": "admin_portal"}},
        "model_profile": {"profile": "standard"},
        "tool_allowlist": [
            "ticket.read",
            "knowledge.search",
            "draft.create",
            "ticket.sync",
        ],
    }


def test_production_manual_employee_requires_activation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        employee_service,
        "get_settings",
        lambda: Settings(
            app_env="production",
            app_auth_mode="oidc",
            oidc_issuer_url="https://issuer.example",
            oidc_audience="ticket-agent",
        ),
    )
    created = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json=_employee_payload("production_trial_employee"),
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "TRIAL"

    bypass = client.patch(
        f"/api/v1/digital-employees/{created.json()['id']}",
        headers=ADMIN,
        json={"status": "ACTIVE"},
    )
    assert bypass.status_code == 409
    assert bypass.json()["code"] == "EMPLOYEE_ACTIVATION_REQUIRED"

    from_template = client.post(
        "/api/v1/digital-employees/from-template",
        headers=ADMIN,
        json={
            "name": "生产模板员工",
            "template_code": "ecommerce_presales",
            "business_unit_id": "bu_demo",
        },
    )
    assert from_template.status_code == 201, from_template.text
    assert from_template.json()["status"] == "TRIAL"
    assert (
        from_template.json()["manifest"]["activation_required"] is True
    )


def _ticket_payload(employee_id: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "business_unit_id": "bu_demo",
        "source": {
            "system": "demo_helpdesk",
            "channel": "web_form",
            "external_ticket_id": "EMPLOYEE-TICKET-001",
        },
        "requester": {
            "external_ref": "customer-employee",
            "customer_tier": "standard",
        },
        "subject": "如何配置企业通知",
        "body": "请问管理员如何配置团队通知？",
        "locale": "zh-CN",
        "attachments": [],
        "metadata": {"product": "admin_portal"},
    }
    if employee_id:
        payload["employee_id"] = employee_id
    return payload


def test_list_does_not_create_unrelated_default_employee(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/v1/digital-employees?business_unit_id=bu_demo",
        headers=AGENT,
    )

    assert response.status_code == 200
    assert response.json() == []


def test_create_employee_and_bind_ticket(client: TestClient) -> None:
    employee = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json=_employee_payload(),
    )
    assert employee.status_code == 201
    employee_id = employee.json()["id"]

    created = client.post(
        "/api/v1/tickets",
        headers={**AGENT, "Idempotency-Key": "employee:001"},
        json=_ticket_payload(employee_id),
    )
    assert created.status_code == 202
    assert created.json()["employee_id"] == employee_id
    detail = client.get(
        f"/api/v1/tickets/{created.json()['id']}",
        headers=AGENT,
    )
    assert detail.status_code == 200
    assert detail.json()["employee"]["name"] == "二级客服数字员工"
    assert detail.json()["employee"]["workflow_key"] == "customer_service_ticket_v1"


def test_employee_instruction_is_versioned_with_configuration(
    client: TestClient,
) -> None:
    payload = _employee_payload("instruction_employee")
    payload["instruction"] = "你是一名耐心、简洁的售后客服。"
    created = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json=payload,
    )
    assert created.status_code == 201, created.text
    employee = created.json()
    assert employee["instruction"] == "你是一名耐心、简洁的售后客服。"

    revisions = client.get(
        f"/api/v1/digital-employees/{employee['id']}/revisions",
        headers=AGENT,
    )
    assert revisions.status_code == 200
    assert revisions.json()[0]["instruction"] == "你是一名耐心、简洁的售后客服。"

    configured = client.put(
        f"/api/v1/digital-employees/{employee['id']}/configuration",
        headers=ADMIN,
        json={"instruction": "先确认订单号，再给结论。"},
    )
    assert configured.status_code == 200, configured.text
    assert configured.json()["instruction"] == "先确认订单号，再给结论。"
    assert configured.json()["config_revision"] == employee["config_revision"] + 1

    revisions = client.get(
        f"/api/v1/digital-employees/{employee['id']}/revisions",
        headers=AGENT,
    )
    assert revisions.json()[0]["instruction"] == "先确认订单号，再给结论。"

    too_long = client.patch(
        f"/api/v1/digital-employees/{employee['id']}",
        headers=ADMIN,
        json={"instruction": "长" * 4001},
    )
    assert too_long.status_code == 422


def test_create_employee_from_template_with_manifest_and_revision(
    client: TestClient,
) -> None:
    templates = client.get(
        "/api/v1/digital-employee-templates",
        headers=AGENT,
    )
    assert templates.status_code == 200
    assert {
        item["code"] for item in templates.json()
    } == {
        "enterprise_service_desk",
        "ecommerce_presales",
        "ecommerce_aftersales",
        "ecommerce_logistics",
            "ecommerce_listing_operator",
            "ecommerce_visual_creator",
            "ecommerce_operations_supervisor",
        "hr_onboarding",
        "customer_service_supervisor",
    }

    created = client.post(
        "/api/v1/digital-employees/from-template",
        headers=ADMIN,
        json={
            "name": "保温杯售前助手",
            "template_code": "ecommerce_presales",
            "business_unit_id": "bu_demo",
        },
    )
    assert created.status_code == 201, created.text
    employee = created.json()
    assert employee["domain"] == "customer_service"
    assert employee["template_code"] == "ecommerce_presales"
    assert employee["config_revision"] == 1
    assert employee["manifest"]["template_code"] == "ecommerce_presales"
    assert employee["manifest"]["routing"]["deterministic_first"] is True

    skills = client.get(
        f"/api/v1/digital-employees/{employee['id']}/skills",
        headers=AGENT,
    )
    assert skills.status_code == 200
    assert [item["skill_code"] for item in skills.json()] == [
        "ecommerce-presales"
    ]

    revisions = client.get(
        f"/api/v1/digital-employees/{employee['id']}/revisions",
        headers=AGENT,
    )
    assert revisions.status_code == 200
    assert len(revisions.json()) == 1
    assert revisions.json()[0]["status"] == "PUBLISHED"

    updated = client.patch(
        f"/api/v1/digital-employees/{employee['id']}",
        headers=ADMIN,
        json={"name": "保温杯购买顾问"},
    )
    assert updated.status_code == 200
    assert updated.json()["config_revision"] == 2
    revisions = client.get(
        f"/api/v1/digital-employees/{employee['id']}/revisions",
        headers=AGENT,
    )
    assert len(revisions.json()) == 2


def test_ticket_without_employee_routes_to_specialist(
    client: TestClient,
) -> None:
    presales = client.post(
        "/api/v1/digital-employees/from-template",
        headers=ADMIN,
        json={
            "name": "售前路由测试",
            "template_code": "ecommerce_presales",
            "business_unit_id": "bu_demo",
        },
    )
    aftersales = client.post(
        "/api/v1/digital-employees/from-template",
        headers=ADMIN,
        json={
            "name": "售后路由测试",
            "template_code": "ecommerce_aftersales",
            "business_unit_id": "bu_demo",
        },
    )
    assert presales.status_code == 201, presales.text
    assert aftersales.status_code == 201, aftersales.text

    def create_ticket(external_id: str, subject: str, body: str) -> dict:
        response = client.post(
            "/api/v1/tickets",
            headers={**AGENT, "Idempotency-Key": f"route:{external_id}"},
            json={
                "business_unit_id": "bu_demo",
                "source": {
                    "system": "route_test",
                    "channel": "web_form",
                    "external_ticket_id": external_id,
                },
                "requester": {
                    "external_ref": "route-buyer",
                    "customer_tier": "standard",
                },
                "subject": subject,
                "body": body,
                "locale": "zh-CN",
                "attachments": [],
                "metadata": {"product": "vacuum_cup"},
            },
        )
        assert response.status_code == 202, response.text
        return response.json()

    presales_ticket = create_ticket(
        "ROUTE-PRESALES-001",
        "保温杯容量和颜色",
        "请问这款保温杯容量多少，有什么颜色？",
    )
    aftersales_ticket = create_ticket(
        "ROUTE-AFTERSALES-001",
        "商品破损退款",
        "商品破损了，我要申请退款退货。",
    )
    assert presales_ticket["employee_id"] == presales.json()["id"]
    assert aftersales_ticket["employee_id"] == aftersales.json()["id"]

    decisions = client.get(
        "/api/v1/digital-employee-route-decisions?business_unit_id=bu_demo",
        headers=AGENT,
    )
    assert decisions.status_code == 200
    selected = {
        item["selected_employee_id"] for item in decisions.json()["items"]
    }
    assert presales.json()["id"] in selected
    assert aftersales.json()["id"] in selected
    assert all(
        item["reason_code"] == "INTENT_MATCH"
        for item in decisions.json()["items"]
    )


def test_disabled_employee_cannot_receive_new_ticket(client: TestClient) -> None:
    employee = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json=_employee_payload("disabled_ticket_employee"),
    ).json()
    disabled = client.patch(
        f"/api/v1/digital-employees/{employee['id']}",
        headers=ADMIN,
        json={"status": "DISABLED"},
    )
    assert disabled.status_code == 200

    created = client.post(
        "/api/v1/tickets",
        headers={**AGENT, "Idempotency-Key": "employee:disabled"},
        json=_ticket_payload(employee["id"]),
    )
    assert created.status_code == 409
    assert created.json()["code"] == "DIGITAL_EMPLOYEE_DISABLED"


def test_unsupported_workflow_is_rejected(client: TestClient) -> None:
    payload = _employee_payload("unsupported_workflow_employee")
    payload["workflow_key"] = "unknown_workflow"

    response = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "UNSUPPORTED_WORKFLOW"


def test_hr_onboarding_workflow_runs_through_shared_platform(
    client: TestClient,
) -> None:
    document = client.post(
        "/api/v1/knowledge-documents",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "title": "新员工入职资料清单",
            "doc_type": "SOP",
            "owner_id": "hr-admin",
            "scope": {"audiences": ["new_employee", "support_agent"]},
        },
    ).json()
    version = client.post(
        f"/api/v1/knowledge-documents/{document['id']}/versions",
        headers=ADMIN,
        json={
            "version_label": "1.0",
            "content": "新员工需提交身份证明、学历证明和银行卡信息，由 HR 审核。",
        },
    ).json()
    client.post(
        f"/api/v1/knowledge-documents/{document['id']}/versions/{version['id']}/publish",
        headers=ADMIN,
        json={"release_note": "hr smoke"},
    ).raise_for_status()

    employee = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json={
            "employee_key": "hr_onboarding_employee",
            "name": "入职资料数字员工",
            "version": "1.0.0",
            "scenario_type": "hr_onboarding",
            "workflow_key": "hr_onboarding_document_collection_v1",
            "business_unit_id": "bu_demo",
            "service_identity": "digital_employee.hr_onboarding",
            "handoff_queue": "HR_SERVICE_DESK",
            "knowledge_policy": {
                "default_scope": {"audiences": "new_employee"},
            },
            "model_profile": {},
            "tool_allowlist": [
                "ticket.read",
                "knowledge.search",
                "draft.create",
                "employee_profile.read",
                "ticket.sync",
            ],
        },
    )
    assert employee.status_code == 201

    created = client.post(
        "/api/v1/tickets",
        headers={**AGENT, "Idempotency-Key": "hr:onboarding:001"},
        json={
            "business_unit_id": "bu_demo",
            "employee_id": employee.json()["id"],
            "source": {
                "system": "hr_portal",
                "channel": "web_form",
                "external_ticket_id": "HR-ONBOARD-001",
            },
            "requester": {
                "external_ref": "new-employee-001",
                "customer_tier": "employee",
            },
            "subject": "新员工入职资料提交",
            "body": "请问入职需要准备哪些资料？",
            "locale": "zh-CN",
            "attachments": [],
            "metadata": {"region": "cn-east"},
        },
    )
    assert created.status_code == 202
    detail = client.get(
        f"/api/v1/tickets/{created.json()['id']}",
        headers=AGENT,
    ).json()
    assert detail["workflow_state"] == "PENDING_REVIEW"
    assert detail["employee"]["workflow_key"] == "hr_onboarding_document_collection_v1"
    assert detail["classification"]["primary"] == "hr_onboarding"
    assert detail["routing"]["queue_id"] == "HR_SERVICE_DESK"
    assert detail["draft"]["citations"][0]["title"] == "新员工入职资料清单"

    reviewed = client.post(
        f"/api/v1/tickets/{created.json()['id']}/reviews",
        headers=AGENT,
        json={
            "expected_version": detail["version"],
            "decision": "ACCEPTED",
            "reason_code": "HR_APPROVED",
        },
    )
    assert reviewed.status_code == 200
    final = client.get(
        f"/api/v1/tickets/{created.json()['id']}",
        headers=AGENT,
    ).json()
    assert final["workflow_state"] == "COMPLETED"
    assert final["sync"]["status"] == "SUCCEEDED"


def test_hr_workflow_without_knowledge_goes_to_human(client: TestClient) -> None:
    employee = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json={
            "employee_key": "hr_no_knowledge_employee",
            "name": "无知识入职数字员工",
            "scenario_type": "hr_onboarding",
            "workflow_key": "hr_onboarding_document_collection_v1",
            "business_unit_id": "bu_demo",
            "service_identity": "digital_employee.hr_no_knowledge",
            "handoff_queue": "HR_SERVICE_DESK",
            "knowledge_policy": {
                "default_scope": {"audiences": "new_employee"},
            },
            "tool_allowlist": [
                "ticket.read",
                "knowledge.search",
                "draft.create",
                "ticket.sync",
            ],
        },
    ).json()
    created = client.post(
        "/api/v1/tickets",
        headers={**AGENT, "Idempotency-Key": "hr:no-knowledge"},
        json={
            "business_unit_id": "bu_demo",
            "employee_id": employee["id"],
            "source": {
                "system": "hr_portal",
                "channel": "web_form",
                "external_ticket_id": "HR-NO-KNOWLEDGE",
            },
            "requester": {
                "external_ref": "new-employee-002",
                "customer_tier": "employee",
            },
            "subject": "入职资料",
            "body": "需要什么资料？",
            "locale": "zh-CN",
            "attachments": [],
            "metadata": {},
        },
    )
    assert created.status_code == 202
    detail = client.get(
        f"/api/v1/tickets/{created.json()['id']}",
        headers=AGENT,
    ).json()
    assert detail["workflow_state"] == "NEEDS_HUMAN"
    assert detail["routing"]["human_reason"] == "HR_SOP_NOT_FOUND"


def test_missing_tool_permission_fails_safe(client: TestClient) -> None:
    employee = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json={
            "employee_key": "limited_tool_employee",
            "name": "受限权限数字员工",
            "scenario_type": "customer_service_ticket",
            "workflow_key": "customer_service_ticket_v1",
            "business_unit_id": "bu_demo",
            "service_identity": "digital_employee.limited",
            "handoff_queue": "LIMITED_QUEUE",
            "tool_allowlist": ["ticket.read"],
        },
    ).json()
    created = client.post(
        "/api/v1/tickets",
        headers={**AGENT, "Idempotency-Key": "employee:limited-tool"},
        json={
            "business_unit_id": "bu_demo",
            "employee_id": employee["id"],
            "source": {
                "system": "demo_helpdesk",
                "channel": "web_form",
                "external_ticket_id": "LIMITED-TOOL-001",
            },
            "requester": {
                "external_ref": "customer-limited",
                "customer_tier": "standard",
            },
            "subject": "需要配置通知",
            "body": "请问如何配置？",
            "locale": "zh-CN",
            "attachments": [],
            "metadata": {},
        },
    )
    assert created.status_code == 202
    detail = client.get(
        f"/api/v1/tickets/{created.json()['id']}",
        headers=AGENT,
    ).json()

    assert detail["workflow_state"] == "NEEDS_HUMAN"
    assert detail["routing"]["human_reason"] == "TOOL_PERMISSION_DENIED"


def test_employee_model_profile_changes_classification_policy(
    client: TestClient,
) -> None:
    employee = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json={
            "employee_key": "strict_classification_employee",
            "name": "严格分类数字员工",
            "scenario_type": "customer_service_ticket",
            "workflow_key": "customer_service_ticket_v1",
            "business_unit_id": "bu_demo",
            "service_identity": "digital_employee.strict",
            "handoff_queue": "STRICT_QUEUE",
            "model_profile": {
                "classification": {"confidence_threshold": 0.99},
            },
            "tool_allowlist": [
                "ticket.read",
                "knowledge.search",
                "draft.create",
                "ticket.sync",
            ],
        },
    ).json()
    created = client.post(
        "/api/v1/tickets",
        headers={**AGENT, "Idempotency-Key": "employee:strict-classifier"},
        json={
            "business_unit_id": "bu_demo",
            "employee_id": employee["id"],
            "source": {
                "system": "demo_helpdesk",
                "channel": "web_form",
                "external_ticket_id": "STRICT-CLASSIFY-001",
            },
            "requester": {
                "external_ref": "customer-strict",
                "customer_tier": "standard",
            },
            "subject": "如何配置团队通知",
            "body": "管理员如何配置团队消息通知？",
            "locale": "zh-CN",
            "attachments": [],
            "metadata": {},
        },
    )
    detail = client.get(
        f"/api/v1/tickets/{created.json()['id']}",
        headers=AGENT,
    ).json()

    assert detail["workflow_state"] == "NEEDS_HUMAN"
    assert detail["routing"]["human_reason"] == "LOW_CLASSIFICATION_CONFIDENCE"


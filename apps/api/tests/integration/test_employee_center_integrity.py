from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ticket_agent.digital_employees.models import (
    DigitalEmployeeManagedTemplate,
)
from ticket_agent.shared.db import SessionLocal

ADMIN = {"X-Actor-Id": "center-admin", "X-Actor-Role": "admin"}
AGENT = {"X-Actor-Id": "center-agent", "X-Actor-Role": "agent"}
EMPLOYEE_VIEWER = {
    "X-Actor-Id": "center-employee-viewer",
    "X-Actor-Role": "knowledge_operator",
}


def _employee(
    client: TestClient,
    *,
    template_code: str = "ecommerce_presales",
    name: str = "数字员工中心测试",
) -> dict:
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


def _space(client: TestClient, code: str) -> dict:
    response = client.post(
        "/api/v1/knowledge-spaces",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "code": code,
            "name": code,
            "domain": "customer_service",
            "owner_id": "center-admin",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_employee_configuration_is_atomic_and_reactivation_is_enforced(
    client: TestClient,
) -> None:
    employee = _employee(client)
    space = _space(client, f"atomic_space_{uuid4().hex[:6]}")
    skills = client.get(
        "/api/v1/skills?business_unit_id=bu_demo",
        headers=AGENT,
    ).json()
    skill = next(
        item for item in skills if item["code"] == "ecommerce-presales"
    )

    configured = client.put(
        f"/api/v1/digital-employees/{employee['id']}/configuration",
        headers=ADMIN,
        json={
            "name": "原子配置员工",
            "handoff_queue": "CENTER_QUEUE",
            "tool_allowlist": employee["tool_allowlist"],
            "knowledge_bindings": [
                {
                    "knowledge_space_id": space["id"],
                    "enabled": True,
                }
            ],
            "skill_bindings": [
                {
                    "skill_id": skill["id"],
                    "enabled": True,
                }
            ],
            "mcp_bindings": [],
        },
    )
    assert configured.status_code == 200, configured.text
    assert configured.json()["status"] == "TRIAL"
    assert configured.json()["name"] == "原子配置员工"

    activated = client.post(
        f"/api/v1/digital-employees/{employee['id']}/activate",
        headers=ADMIN,
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "ACTIVE"

    renamed = client.patch(
        f"/api/v1/digital-employees/{employee['id']}",
        headers=ADMIN,
        json={"name": "仅改名保持启用"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["status"] == "ACTIVE"

    resource_removed = client.put(
        f"/api/v1/digital-employees/{employee['id']}/configuration",
        headers=ADMIN,
        json={"knowledge_bindings": []},
    )
    assert resource_removed.status_code == 200, resource_removed.text
    assert resource_removed.json()["status"] == "TRIAL"

    direct_enable = client.patch(
        f"/api/v1/digital-employees/{employee['id']}",
        headers=ADMIN,
        json={"status": "ACTIVE"},
    )
    assert direct_enable.status_code == 409
    assert direct_enable.json()["code"] == "EMPLOYEE_ACTIVATION_REQUIRED"

    failed_activation = client.post(
        f"/api/v1/digital-employees/{employee['id']}/activate",
        headers=ADMIN,
    )
    assert failed_activation.status_code == 200
    assert failed_activation.json()["status"] == "EVALUATION_FAILED"

    duplicate_skills = client.put(
        f"/api/v1/digital-employees/{employee['id']}/configuration",
        headers=ADMIN,
        json={
            "name": "不应写入的名称",
            "skill_bindings": [
                {"skill_id": skill["id"], "enabled": True},
                {"skill_id": skill["id"], "enabled": True},
            ],
        },
    )
    assert duplicate_skills.status_code == 422
    assert duplicate_skills.json()["code"] == "SKILL_BINDING_DUPLICATED"
    current = client.get(
        "/api/v1/digital-employees?business_unit_id=bu_demo",
        headers=EMPLOYEE_VIEWER,
    ).json()
    stored = next(item for item in current if item["id"] == employee["id"])
    assert stored["name"] == "仅改名保持启用"

    restored = client.put(
        f"/api/v1/digital-employees/{employee['id']}/configuration",
        headers=ADMIN,
        json={
            "knowledge_bindings": [
                {
                    "knowledge_space_id": space["id"],
                    "enabled": True,
                }
            ]
        },
    )
    assert restored.status_code == 200, restored.text
    reactivated = client.post(
        f"/api/v1/digital-employees/{employee['id']}/activate",
        headers=ADMIN,
    )
    assert reactivated.status_code == 200
    assert reactivated.json()["status"] == "ACTIVE"

    disabled = client.patch(
        f"/api/v1/digital-employees/{employee['id']}",
        headers=ADMIN,
        json={"status": "DISABLED"},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["status"] == "DISABLED"
    reenabled = client.post(
        f"/api/v1/digital-employees/{employee['id']}/activate",
        headers=ADMIN,
    )
    assert reenabled.status_code == 200, reenabled.text
    assert reenabled.json()["status"] == "ACTIVE"


def test_duplicate_bindings_are_rejected_without_partial_writes(
    client: TestClient,
) -> None:
    employee = _employee(client)
    employee_id = employee["id"]
    skill_id = client.get(
        "/api/v1/skills?business_unit_id=bu_demo",
        headers=AGENT,
    ).json()[0]["id"]
    duplicate_skill = client.put(
        f"/api/v1/digital-employees/{employee_id}/skills",
        headers=ADMIN,
        json={
            "bindings": [
                {"skill_id": skill_id, "enabled": True},
                {"skill_id": skill_id, "enabled": True},
            ]
        },
    )
    assert duplicate_skill.status_code == 422
    assert duplicate_skill.json()["code"] == "SKILL_BINDING_DUPLICATED"

    space = _space(client, f"duplicate_space_{uuid4().hex[:6]}")
    duplicate_knowledge = client.put(
        f"/api/v1/digital-employees/{employee_id}/knowledge-bindings",
        headers=ADMIN,
        json={
            "bindings": [
                {
                    "knowledge_space_id": space["id"],
                    "workflow_key": "customer_service_ticket_v1",
                    "enabled": True,
                },
                {
                    "knowledge_space_id": space["id"],
                    "workflow_key": "customer_service_ticket_v1",
                    "enabled": True,
                },
            ]
        },
    )
    assert duplicate_knowledge.status_code == 422
    assert (
        duplicate_knowledge.json()["code"]
        == "KNOWLEDGE_BINDING_DUPLICATED"
    )
    assert client.get(
        f"/api/v1/digital-employees/{employee_id}/knowledge-bindings",
        headers=AGENT,
    ).json() == []

    connector = client.post(
        "/api/v1/mcp/connectors",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "code": f"duplicate-{uuid4().hex[:6]}",
            "name": "重复绑定测试",
            "url": "http://127.0.0.1:9/mcp",
            "timeout_seconds": 1,
        },
    )
    assert connector.status_code == 201, connector.text
    duplicate_mcp = client.put(
        f"/api/v1/digital-employees/{employee_id}/mcp-connectors",
        headers=ADMIN,
        json={
            "bindings": [
                {
                    "connector_id": connector.json()["id"],
                    "enabled": True,
                },
                {
                    "connector_id": connector.json()["id"],
                    "enabled": True,
                },
            ]
        },
    )
    assert duplicate_mcp.status_code == 422
    assert duplicate_mcp.json()["code"] == "MCP_BINDING_DUPLICATED"


def test_skill_change_moves_bound_active_employee_back_to_trial(
    client: TestClient,
) -> None:
    employee = _employee(client)
    skill = client.get(
        "/api/v1/skills?business_unit_id=bu_demo",
        headers=AGENT,
    ).json()
    presales = next(
        item for item in skill if item["code"] == "ecommerce-presales"
    )
    updated = client.patch(
        f"/api/v1/skills/{presales['id']}",
        headers=ADMIN,
        json={"instructions": "更新后的售前规程，必须重新核验员工。"},
    )
    assert updated.status_code == 200, updated.text
    employees = client.get(
        "/api/v1/digital-employees?business_unit_id=bu_demo",
        headers=EMPLOYEE_VIEWER,
    ).json()
    stored = next(item for item in employees if item["id"] == employee["id"])
    assert stored["status"] == "TRIAL"
    assert stored["config_revision"] > employee["config_revision"]


def test_template_publish_is_blocked_when_required_resources_are_missing(
    client: TestClient,
) -> None:
    with SessionLocal() as session:
        template = DigitalEmployeeManagedTemplate(
            business_unit_id="bu_demo",
            code=f"invalid_{uuid4().hex[:8]}",
            name="缺资源模板",
            description="不应发布",
            domain="customer_service",
            workflow_key="customer_service_ticket_v1",
            scenario_type="customer_service_ticket",
            handoff_queue="MANUAL_TRIAGE",
            capabilities_json=["测试能力"],
            intents_json=["测试"],
            skill_codes_json=["missing-skill"],
            tool_allowlist_json=["ticket.read"],
            knowledge_bindings_json=[],
            mcp_bindings_json=[],
            model_profile_json={},
            knowledge_policy_json={},
            readiness_snapshot_json={},
            status="DRAFT",
            created_by="center-admin",
        )
        session.add(template)
        session.commit()
        template_id = template.id

    approved = client.post(
        f"/api/v1/digital-employee-templates/{template_id}/review",
        headers=ADMIN,
        json={"decision": "APPROVE", "note": "结构通过"},
    )
    assert approved.status_code == 200, approved.text
    publish = client.post(
        f"/api/v1/digital-employee-templates/{template_id}/publish",
        headers=ADMIN,
    )
    assert publish.status_code == 409
    assert publish.json()["code"] == "EMPLOYEE_TEMPLATE_NOT_READY"
    assert "missing-skill" in publish.json()["detail"]


def test_published_template_clone_fails_when_required_knowledge_is_disabled(
    client: TestClient,
) -> None:
    space = _space(client, f"template_drift_{uuid4().hex[:6]}")
    client.get(
        "/api/v1/skills?business_unit_id=bu_demo",
        headers=AGENT,
    ).raise_for_status()
    with SessionLocal() as session:
        template = DigitalEmployeeManagedTemplate(
            business_unit_id="bu_demo",
            code=f"drift_{uuid4().hex[:8]}",
            name="资源漂移模板",
            description="验证发布后资源失效",
            domain="customer_service",
            workflow_key="customer_service_ticket_v1",
            scenario_type="customer_service_ticket",
            handoff_queue="MANUAL_TRIAGE",
            capabilities_json=["商品咨询"],
            intents_json=["商品"],
            skill_codes_json=["ecommerce-presales"],
            tool_allowlist_json=["ticket.read", "knowledge.search"],
            knowledge_bindings_json=[
                {
                    "knowledge_space_id": space["id"],
                    "enabled": True,
                }
            ],
            mcp_bindings_json=[],
            model_profile_json={},
            knowledge_policy_json={},
            readiness_snapshot_json={},
            status="DRAFT",
            created_by="center-admin",
        )
        session.add(template)
        session.commit()
        template_id = template.id
        template_code = template.code

    reviewed = client.post(
        f"/api/v1/digital-employee-templates/{template_id}/review",
        headers=ADMIN,
        json={"decision": "APPROVE", "note": "资源完整"},
    )
    assert reviewed.status_code == 200, reviewed.text
    published = client.post(
        f"/api/v1/digital-employee-templates/{template_id}/publish",
        headers=ADMIN,
    )
    assert published.status_code == 200, published.text

    disabled = client.patch(
        f"/api/v1/knowledge-spaces/{space['id']}",
        headers=ADMIN,
        json={"status": "DISABLED"},
    )
    assert disabled.status_code == 200, disabled.text
    clone = client.post(
        "/api/v1/digital-employees/from-template",
        headers=ADMIN,
        json={
            "name": "不应创建的无知员工",
            "template_code": template_code,
            "business_unit_id": "bu_demo",
        },
    )
    assert clone.status_code == 409
    assert (
        clone.json()["code"]
        == "EMPLOYEE_TEMPLATE_KNOWLEDGE_UNAVAILABLE"
    )


def test_workforce_reassess_reroutes_after_new_employee_is_created(
    client: TestClient,
) -> None:
    _employee(
        client,
        template_code="customer_service_supervisor",
        name="任务主管",
    )
    task = client.post(
        "/api/v1/workforce/tasks",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "title": "入职资料复核",
            "objective": "协助新员工完成入职资料收集和劳动合同材料检查。",
        },
    )
    assert task.status_code == 201, task.text
    assert task.json()["capability_gaps"]

    hr = _employee(
        client,
        template_code="hr_onboarding",
        name="HR 入职专员",
    )
    reassessed = client.post(
        f"/api/v1/workforce/tasks/{task.json()['id']}/reassess",
        headers=AGENT,
    )
    assert reassessed.status_code == 200, reassessed.text
    assert reassessed.json()["capability_gaps"] == []
    assert {
        step["assigned_employee_id"]
        for step in reassessed.json()["steps"]
    } == {hr["id"]}


def test_workforce_rejects_employee_without_supervisor_capability(
    client: TestClient,
) -> None:
    specialist = _employee(
        client,
        template_code="ecommerce_presales",
        name="普通售前员工",
    )
    task = client.post(
        "/api/v1/workforce/tasks",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "title": "错误主管",
            "objective": "分析复杂问题并汇总处理建议。",
            "supervisor_employee_id": specialist["id"],
        },
    )
    assert task.status_code == 422
    assert (
        task.json()["code"]
        == "WORKFORCE_SUPERVISOR_CAPABILITY_REQUIRED"
    )


def test_workforce_execute_is_idempotent_while_queued(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supervisor = _employee(
        client,
        template_code="customer_service_supervisor",
        name="幂等主管",
    )
    task = client.post(
        "/api/v1/workforce/tasks",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "title": "主管协调汇总任务",
            "objective": "复杂问题需要主管协调、统一处理和汇总。",
            "supervisor_employee_id": supervisor["id"],
        },
    )
    assert task.status_code == 201, task.text
    assert task.json()["capability_gaps"] == []

    calls: list[str] = []

    def fake_job(task_id: object, correlation_id: str) -> None:
        calls.append(str(task_id))

    monkeypatch.setattr(
        "ticket_agent.workforce.router.execute_workforce_task_job",
        fake_job,
    )
    first = client.post(
        f"/api/v1/workforce/tasks/{task.json()['id']}/execute",
        headers=AGENT,
    )
    assert first.status_code == 200, first.text
    second = client.post(
        f"/api/v1/workforce/tasks/{task.json()['id']}/execute",
        headers=AGENT,
    )
    assert second.status_code == 200, second.text
    assert len(calls) == 1

    invalid_retry = client.post(
        f"/api/v1/workforce/tasks/{task.json()['id']}/retry",
        headers=AGENT,
    )
    assert invalid_retry.status_code == 409
    assert (
        invalid_retry.json()["code"]
        == "WORKFORCE_TASK_NOT_RETRYABLE"
    )

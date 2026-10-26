from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from ticket_agent.mcp_connectors.models import (
    McpActionIncident,
    McpToolApproval,
)
from ticket_agent.shared.db import SessionLocal

ALPHA_ADMIN = {
    "X-Actor-Id": "alpha-admin",
    "X-Actor-Role": "admin",
    "X-Business-Unit-Id": "bu_alpha",
}
ALPHA_AGENT = {
    "X-Actor-Id": "alpha-agent",
    "X-Actor-Role": "agent",
    "X-Business-Unit-Id": "bu_alpha",
}
BETA_ADMIN = {
    "X-Actor-Id": "beta-admin",
    "X-Actor-Role": "admin",
    "X-Business-Unit-Id": "bu_beta",
}


def test_tenant_query_scope_is_enforced(
    client: TestClient,
) -> None:
    own = client.get(
        "/api/v1/digital-employees?business_unit_id=bu_alpha",
        headers=ALPHA_AGENT,
    )
    assert own.status_code == 200

    foreign = client.get(
        "/api/v1/digital-employees?business_unit_id=bu_beta",
        headers=ALPHA_AGENT,
    )
    assert foreign.status_code == 403
    assert foreign.json()["code"] == "BUSINESS_UNIT_ACCESS_DENIED"

    knowledge = client.get(
        "/api/v1/knowledge-spaces?business_unit_id=bu_beta",
        headers=ALPHA_AGENT,
    )
    assert knowledge.status_code == 403

    foreign_body = client.post(
        "/api/v1/knowledge-documents",
        headers=ALPHA_ADMIN,
        json={
            "business_unit_id": "bu_beta",
            "title": "跨租户文档",
            "doc_type": "SOP",
            "owner_id": "alpha-admin",
        },
    )
    assert foreign_body.status_code == 403
    assert foreign_body.json()["code"] == "BUSINESS_UNIT_ACCESS_DENIED"


def test_tenant_resource_access_is_enforced(
    client: TestClient,
) -> None:
    employee = client.post(
        "/api/v1/digital-employees/from-template",
        headers=ALPHA_ADMIN,
        json={
            "name": "Alpha 客服",
            "template_code": "ecommerce_presales",
            "business_unit_id": "bu_alpha",
        },
    )
    assert employee.status_code == 201, employee.text
    employee_id = employee.json()["id"]

    foreign_employee = client.get(
        f"/api/v1/digital-employees/{employee_id}/revisions",
        headers=BETA_ADMIN,
    )
    assert foreign_employee.status_code == 403

    task = client.post(
        "/api/v1/workforce/tasks",
        headers=ALPHA_AGENT,
        json={
            "business_unit_id": "bu_alpha",
            "title": "Alpha 入职任务",
            "objective": "协助新员工办理入职资料。",
        },
    )
    assert task.status_code == 201, task.text
    task_id = task.json()["id"]
    gap = task.json()["capability_gaps"][0]
    draft = client.post(
        f"/api/v1/workforce/tasks/{task_id}/capability-drafts",
        headers=ALPHA_ADMIN,
        json={
            "required_capability": gap["required_capability"],
            "name": "Alpha 入职草案",
        },
    )
    assert draft.status_code == 201, draft.text
    draft_id = draft.json()["id"]

    foreign_task = client.get(
        f"/api/v1/workforce/tasks/{task_id}",
        headers=BETA_ADMIN,
    )
    assert foreign_task.status_code == 403
    foreign_reassess = client.post(
        f"/api/v1/workforce/tasks/{task_id}/reassess",
        headers=BETA_ADMIN,
    )
    assert foreign_reassess.status_code == 403
    foreign_draft = client.get(
        f"/api/v1/digital-employee-drafts/{draft_id}",
        headers=BETA_ADMIN,
    )
    assert foreign_draft.status_code == 403
    foreign_draft_revisions = client.get(
        f"/api/v1/digital-employee-drafts/{draft_id}/revisions",
        headers=BETA_ADMIN,
    )
    assert foreign_draft_revisions.status_code == 403
    foreign_configuration = client.put(
        f"/api/v1/digital-employees/{employee_id}/configuration",
        headers=BETA_ADMIN,
        json={"name": "跨租户配置"},
    )
    assert foreign_configuration.status_code == 403

    foreign_template_create = client.post(
        "/api/v1/digital-employees/from-template",
        headers=ALPHA_ADMIN,
        json={
            "name": "越界员工",
            "template_code": "ecommerce_presales",
            "business_unit_id": "bu_beta",
        },
    )
    assert foreign_template_create.status_code == 403


def test_knowledge_and_mcp_resources_are_tenant_isolated(
    client: TestClient,
) -> None:
    alpha_space = client.post(
        "/api/v1/knowledge-spaces",
        headers=ALPHA_ADMIN,
        json={
            "business_unit_id": "bu_alpha",
            "code": "alpha_private_knowledge",
            "name": "Alpha 私有知识",
            "domain": "customer_service",
            "owner_id": "alpha-admin",
        },
    )
    assert alpha_space.status_code == 201, alpha_space.text
    beta_space = client.post(
        "/api/v1/knowledge-spaces",
        headers=BETA_ADMIN,
        json={
            "business_unit_id": "bu_beta",
            "code": "beta_private_knowledge",
            "name": "Beta 私有知识",
            "domain": "customer_service",
            "owner_id": "beta-admin",
        },
    )
    assert beta_space.status_code == 201, beta_space.text

    scoped_spaces = client.get(
        "/api/v1/knowledge-spaces",
        headers=ALPHA_ADMIN,
    )
    assert scoped_spaces.status_code == 200
    assert {
        item["business_unit_id"] for item in scoped_spaces.json()
    } == {"bu_alpha"}

    foreign_space_update = client.patch(
        f"/api/v1/knowledge-spaces/{beta_space.json()['id']}",
        headers=ALPHA_ADMIN,
        json={"name": "越权修改"},
    )
    assert foreign_space_update.status_code == 403

    employee = client.post(
        "/api/v1/digital-employees/from-template",
        headers=ALPHA_ADMIN,
        json={
            "name": "Alpha 知识隔离员工",
            "template_code": "ecommerce_presales",
            "business_unit_id": "bu_alpha",
        },
    )
    assert employee.status_code == 201, employee.text
    employee_id = employee.json()["id"]

    foreign_binding_read = client.get(
        f"/api/v1/digital-employees/{employee_id}/knowledge-bindings",
        headers=BETA_ADMIN,
    )
    assert foreign_binding_read.status_code == 403
    foreign_binding_write = client.put(
        f"/api/v1/digital-employees/{employee_id}/knowledge-bindings",
        headers=BETA_ADMIN,
        json={
            "bindings": [
                {
                    "knowledge_space_id": beta_space.json()["id"],
                    "enabled": True,
                }
            ]
        },
    )
    assert foreign_binding_write.status_code == 403

    with SessionLocal() as session:
        approval = McpToolApproval(
            business_unit_id="bu_alpha",
            employee_id=UUID(employee_id),
            connector_id=uuid4(),
            tool_id="tenant-test.refund",
            connector_code="tenant-test",
            tool_name="refund",
            arguments_json={"order_id": "ALPHA-1"},
            execution_arguments_json={"order_id": "ALPHA-1"},
            policy_json={},
            request_fingerprint=uuid4().hex,
            requested_by="alpha-requester",
            request_correlation_id="tenant-approval",
            status="PENDING",
        )
        session.add(approval)
        session.flush()
        incident = McpActionIncident(
            business_unit_id="bu_alpha",
            approval_id=approval.id,
            employee_id=UUID(employee_id),
            tool_id=approval.tool_id,
            failure_class="EXECUTION_UNKNOWN",
            status="OPEN",
            required_action="核对外部执行结果",
        )
        session.add(incident)
        session.commit()
        approval_id = approval.id
        incident_id = incident.id

    foreign_approval = client.post(
        f"/api/v1/mcp/tool-approvals/{approval_id}/decisions",
        headers={
            **BETA_ADMIN,
            "X-Actor-Id": "beta-supervisor",
            "X-Actor-Role": "supervisor",
        },
        json={
            "decision": "APPROVE",
            "expected_version": 1,
            "note": "cross tenant",
        },
    )
    assert foreign_approval.status_code == 403
    assert (
        foreign_approval.json()["code"]
        == "BUSINESS_UNIT_ACCESS_DENIED"
    )

    foreign_incident = client.post(
        f"/api/v1/mcp/action-incidents/{incident_id}/acknowledge",
        headers={
            **BETA_ADMIN,
            "X-Actor-Id": "beta-supervisor",
            "X-Actor-Role": "supervisor",
        },
        json={"expected_version": 1, "note": "cross tenant"},
    )
    assert foreign_incident.status_code == 403

    with SessionLocal() as session:
        assert session.get(McpToolApproval, approval_id).status == "PENDING"
        assert session.get(McpActionIncident, incident_id).status == "OPEN"


def test_workforce_rejects_cross_tenant_supervisor(
    client: TestClient,
) -> None:
    beta_supervisor = client.post(
        "/api/v1/digital-employees/from-template",
        headers=BETA_ADMIN,
        json={
            "name": "Beta 主管",
            "template_code": "customer_service_supervisor",
            "business_unit_id": "bu_beta",
        },
    )
    assert beta_supervisor.status_code == 201, beta_supervisor.text

    task = client.post(
        "/api/v1/workforce/tasks",
        headers=ALPHA_ADMIN,
        json={
            "business_unit_id": "bu_alpha",
            "title": "跨租户主管校验",
            "objective": "分析客户问题并生成处理建议。",
            "supervisor_employee_id": beta_supervisor.json()["id"],
        },
    )
    assert task.status_code == 422
    assert (
        task.json()["code"]
        == "WORKFORCE_SUPERVISOR_UNIT_MISMATCH"
    )

import pytest
from fastapi.testclient import TestClient

from ticket_agent.digital_employees import draft_service
from ticket_agent.shared.settings import Settings

ADMIN = {"X-Actor-Id": "draft-admin", "X-Actor-Role": "admin"}
AGENT = {"X-Actor-Id": "draft-agent", "X-Actor-Role": "agent"}


def _create_template(
    client: TestClient,
    code: str,
    name: str,
) -> dict:
    response = client.post(
        "/api/v1/digital-employees/from-template",
        headers=ADMIN,
        json={
            "name": name,
            "template_code": code,
            "business_unit_id": "bu_demo",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_finance_draft(
    client: TestClient,
) -> dict:
    _create_template(
        client,
        "customer_service_supervisor",
        "客服主管",
    )
    task = client.post(
        "/api/v1/workforce/tasks",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "title": "退款财务能力草案",
            "objective": """
客户要求退款。
财务处理能力：生成退款单，并走加急审批流。
""",
            "context": {"order_id": "ORD-DRAFT-REJECT"},
        },
    ).json()
    created = client.post(
        f"/api/v1/workforce/tasks/{task['id']}/capability-drafts",
        headers=ADMIN,
        json={
            "required_capability": "财务处理能力",
            "name": "退款财务专员草案",
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


def test_employee_draft_rejection_is_auditable_and_reopenable(
    client: TestClient,
) -> None:
    draft = _create_finance_draft(client)
    assert draft["revision"] == 1
    edited = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/edit",
        headers=ADMIN,
        json={
            "name": "退款财务专员修订版",
            "capabilities": ["退款单审核", "财务审批协同"],
            "intents": ["退款单", "审批"],
            "skill_codes": ["ecommerce-aftersales"],
            "tool_allowlist": ["ticket.read", "knowledge.search"],
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["name"] == "退款财务专员修订版"
    assert edited.json()["capabilities"] == [
        "退款单审核",
        "财务审批协同",
    ]
    assert edited.json()["revision"] == 2

    forbidden = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/review",
        headers=AGENT,
        json={"decision": "APPROVE", "note": ""},
    )
    assert forbidden.status_code == 403

    missing_reason = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/review",
        headers=ADMIN,
        json={"decision": "REJECT", "note": "   "},
    )
    assert missing_reason.status_code == 422
    assert (
        missing_reason.json()["code"]
        == "EMPLOYEE_DRAFT_REJECTION_REASON_REQUIRED"
    )

    invalid_reopen = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/reopen",
        headers=ADMIN,
    )
    assert invalid_reopen.status_code == 409
    assert invalid_reopen.json()["code"] == "EMPLOYEE_DRAFT_NOT_REJECTED"

    rejected = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/review",
        headers=ADMIN,
        json={
            "decision": "REJECT",
            "note": "缺少退款审批边界，需要补充",
        },
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "REJECTED"
    assert rejected.json()["review_note"] == "缺少退款审批边界，需要补充"

    trial = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/trial",
        headers=ADMIN,
    )
    assert trial.status_code == 409
    assert trial.json()["code"] == "EMPLOYEE_DRAFT_NOT_APPROVED"

    publish = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/publish",
        headers=ADMIN,
    )
    assert publish.status_code == 409
    assert publish.json()["code"] == "EMPLOYEE_DRAFT_EVALUATION_REQUIRED"

    repeated_review = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/review",
        headers=ADMIN,
        json={"decision": "APPROVE", "note": ""},
    )
    assert repeated_review.status_code == 409
    assert repeated_review.json()["code"] == "EMPLOYEE_DRAFT_STATE_CONFLICT"

    reopened = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/reopen",
        headers=ADMIN,
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "DRAFT"
    assert reopened.json()["reviewed_by"] is None
    assert "Reopened by" in reopened.json()["review_note"]

    approved = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/review",
        headers=ADMIN,
        json={"decision": "APPROVE", "note": "补充边界后批准"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"
    assert approved.json()["revision"] == 5
    locked_edit = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/edit",
        headers=ADMIN,
        json={"name": "批准后不应修改"},
    )
    assert locked_edit.status_code == 409
    assert locked_edit.json()["code"] == "EMPLOYEE_DRAFT_NOT_EDITABLE"

    revisions = client.get(
        f"/api/v1/digital-employee-drafts/{draft['id']}/revisions",
        headers=AGENT,
    )
    assert revisions.status_code == 200, revisions.text
    history = revisions.json()
    assert [item["revision"] for item in history] == [5, 4, 3, 2, 1]
    assert [item["status"] for item in history] == [
        "APPROVED",
        "DRAFT",
        "REJECTED",
        "DRAFT",
        "DRAFT",
    ]
    assert history[2]["snapshot"]["review_note"] == (
        "缺少退款审批边界，需要补充"
    )


def test_employee_draft_revision_can_be_restored(
    client: TestClient,
) -> None:
    draft = _create_finance_draft(client)
    assert draft["revision"] == 1
    edited = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/edit",
        headers=ADMIN,
        json={
            "name": "退款财务专员 v2",
            "capabilities": ["退款审核", "财务复核"],
            "intents": ["退款审核"],
            "skill_codes": ["refund-finance"],
            "tool_allowlist": ["ticket.read", "orders.read"],
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["revision"] == 2

    history = client.get(
        f"/api/v1/digital-employee-drafts/{draft['id']}/revisions",
        headers=AGENT,
    ).json()
    initial = next(item for item in history if item["revision"] == 1)
    assert initial["snapshot"]["name"] == draft["name"]
    assert initial["snapshot"]["capabilities"] == draft["capabilities"]
    assert initial["snapshot"]["tool_allowlist"] == draft["tool_allowlist"]

    forbidden = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}"
        "/revisions/1/restore",
        headers=AGENT,
    )
    assert forbidden.status_code == 403

    missing = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}"
        "/revisions/999/restore",
        headers=ADMIN,
    )
    assert missing.status_code == 404
    assert (
        missing.json()["code"]
        == "EMPLOYEE_DRAFT_REVISION_NOT_FOUND"
    )

    restored = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}"
        "/revisions/1/restore",
        headers=ADMIN,
    )
    assert restored.status_code == 200, restored.text
    restored_draft = restored.json()
    assert restored_draft["status"] == "DRAFT"
    assert restored_draft["revision"] == 3
    assert restored_draft["name"] == draft["name"]
    assert restored_draft["capabilities"] == draft["capabilities"]
    assert restored_draft["intents"] == draft["intents"]
    assert restored_draft["skill_codes"] == draft["skill_codes"]
    assert restored_draft["tool_allowlist"] == draft["tool_allowlist"]
    assert restored_draft["required_capability"] == (
        draft["required_capability"]
    )

    restored_history = client.get(
        f"/api/v1/digital-employee-drafts/{draft['id']}/revisions",
        headers=AGENT,
    ).json()
    assert restored_history[0]["revision"] == 3
    assert restored_history[0]["change_note"] == (
        "Employee draft restored from revision 1"
    )

    approved = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/review",
        headers=ADMIN,
        json={"decision": "APPROVE", "note": "回退内容确认"},
    )
    assert approved.status_code == 200
    locked = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}"
        "/revisions/1/restore",
        headers=ADMIN,
    )
    assert locked.status_code == 409
    assert locked.json()["code"] == "EMPLOYEE_DRAFT_NOT_EDITABLE"


def test_employee_draft_publish_requires_evaluation(
    client: TestClient,
) -> None:
    draft = _create_finance_draft(client)
    client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/review",
        headers=ADMIN,
        json={"decision": "APPROVE", "note": ""},
    )
    trial = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/trial",
        headers=ADMIN,
    )
    assert trial.status_code == 200, trial.text

    premature = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/publish",
        headers=ADMIN,
    )
    assert premature.status_code == 409
    assert premature.json()["code"] == "EMPLOYEE_DRAFT_EVALUATION_REQUIRED"

    failed = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/evaluate",
        headers=ADMIN,
    )
    assert failed.status_code == 200
    assert failed.json()["status"] == "EVALUATION_FAILED"
    still_blocked = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/publish",
        headers=ADMIN,
    )
    assert still_blocked.status_code == 409


def test_template_backed_draft_applies_edits_to_trial_employee(
    client: TestClient,
) -> None:
    _create_template(
        client,
        "customer_service_supervisor",
        "客服主管",
    )
    task = client.post(
        "/api/v1/workforce/tasks",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "title": "入职资料专项草案",
            "objective": "协助新员工完成入职资料收集和劳动合同材料检查。",
        },
    )
    assert task.status_code == 201, task.text
    gap = next(
        item
        for item in task.json()["capability_gaps"]
        if item["recommended_template_code"] == "hr_onboarding"
    )
    created = client.post(
        f"/api/v1/workforce/tasks/{task.json()['id']}/capability-drafts",
        headers=ADMIN,
        json={
            "required_capability": gap["required_capability"],
            "name": "入职资料专员草案",
        },
    )
    assert created.status_code == 201, created.text
    draft = created.json()
    assert draft["template_code"] == "hr_onboarding"

    edited = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/edit",
        headers=ADMIN,
        json={
            "name": "入职售后协同专员",
            "capabilities": ["入职资料收集", "售后资料协同"],
            "intents": ["入职", "售后资料"],
            "skill_codes": ["ecommerce-aftersales"],
            "tool_allowlist": ["ticket.read", "knowledge.search"],
        },
    )
    assert edited.status_code == 200, edited.text
    approved = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/review",
        headers=ADMIN,
        json={"decision": "APPROVE", "note": "覆盖范围已确认"},
    )
    assert approved.status_code == 200, approved.text
    trial = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/trial",
        headers=ADMIN,
    )
    assert trial.status_code == 200, trial.text
    employee_id = trial.json()["employee_id"]
    employees = client.get(
        "/api/v1/digital-employees?business_unit_id=bu_demo",
        headers=AGENT,
    )
    assert employees.status_code == 200, employees.text
    body = next(
        item
        for item in employees.json()
        if item["id"] == employee_id
    )
    assert body["name"] == "入职售后协同专员"
    assert body["manifest"]["capabilities"] == [
        "入职资料收集",
        "售后资料协同",
    ]
    assert body["manifest"]["intents"] == ["入职", "售后资料"]
    assert body["manifest"]["required_resources"]["skill_codes"] == [
        "ecommerce-aftersales"
    ]
    assert body["tool_allowlist"] == [
        "ticket.read",
        "knowledge.search",
    ]
    skills = client.get(
        f"/api/v1/digital-employees/{employee_id}/skills",
        headers=AGENT,
    ).json()
    assert [skill["skill_code"] for skill in skills] == [
        "ecommerce-aftersales"
    ]


def test_production_draft_requires_independent_reviewer(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = _create_finance_draft(client)
    monkeypatch.setattr(
        draft_service,
        "get_settings",
        lambda: Settings(
            app_env="production",
            app_auth_mode="oidc",
            oidc_issuer_url="https://issuer.example",
            oidc_audience="ticket-agent",
        ),
    )

    self_review = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/review",
        headers=ADMIN,
        json={"decision": "APPROVE", "note": "self review"},
    )
    assert self_review.status_code == 409
    assert (
        self_review.json()["code"]
        == "SEPARATION_OF_DUTIES_REQUIRED"
    )

    reviewer = {
        **ADMIN,
        "X-Actor-Id": "draft-reviewer",
    }
    independent = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/review",
        headers=reviewer,
        json={"decision": "APPROVE", "note": "independent review"},
    )
    assert independent.status_code == 200
    assert independent.json()["reviewed_by"] == "draft-reviewer"


def test_employee_draft_trial_evaluation_publish_and_rollback(
    client: TestClient,
) -> None:
    _create_template(
        client,
        "customer_service_supervisor",
        "客服主管",
    )
    _create_template(
        client,
        "ecommerce_aftersales",
        "售后专家",
    )
    _create_template(
        client,
        "ecommerce_logistics",
        "物流专家",
    )
    task = client.post(
        "/api/v1/workforce/tasks",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "title": "退款与补发能力草案",
            "objective": """
客户要求退款并补发破损商品。
财务处理能力：生成退款单，并走加急审批流。
""",
            "context": {"order_id": "ORD-DRAFT-1"},
        },
    ).json()
    assert any(
        gap["required_capability"] == "财务处理能力"
        for gap in task["capability_gaps"]
    )

    created = client.post(
        f"/api/v1/workforce/tasks/{task['id']}/capability-drafts",
        headers=ADMIN,
        json={
            "required_capability": "财务处理能力",
            "name": "退款财务专员草案",
        },
    )
    assert created.status_code == 201, created.text
    draft = created.json()
    assert draft["status"] == "DRAFT"
    assert draft["template_code"] is None
    assert draft["reviewed_at"] is None

    duplicate = client.post(
        f"/api/v1/workforce/tasks/{task['id']}/capability-drafts",
        headers=ADMIN,
        json={"required_capability": "财务处理能力"},
    )
    assert duplicate.status_code == 409

    reviewed = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/review",
        headers=ADMIN,
        json={"decision": "APPROVE", "note": "能力范围合理"},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "APPROVED"
    assert reviewed.json()["reviewed_by"] == "draft-admin"

    trial = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/trial",
        headers=ADMIN,
    )
    assert trial.status_code == 200, trial.text
    trial_draft = trial.json()
    assert trial_draft["status"] == "TRIAL"
    employee_id = trial_draft["employee_id"]
    assert employee_id

    employees = client.get(
        "/api/v1/digital-employees?business_unit_id=bu_demo",
        headers=AGENT,
    ).json()
    trial_employee = next(
        employee for employee in employees if employee["id"] == employee_id
    )
    assert trial_employee["status"] == "TRIAL"
    assert trial_employee["name"] == "退款财务专员草案"

    failed_evaluation = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/evaluate",
        headers=ADMIN,
    )
    assert failed_evaluation.status_code == 200
    assert failed_evaluation.json()["status"] == "EVALUATION_FAILED"
    failed_checks = {
        check["key"]: check["status"]
        for check in failed_evaluation.json()["evaluation"]["checks"]
    }
    assert failed_checks["skills"] == "FAILED"
    assert failed_checks["knowledge"] == "FAILED"

    skills = client.get(
        "/api/v1/skills?business_unit_id=bu_demo",
        headers=ADMIN,
    ).json()
    bound_skills = client.put(
        f"/api/v1/digital-employees/{employee_id}/skills",
        headers=ADMIN,
        json={
            "bindings": [
                {
                    "skill_id": skills[0]["id"],
                    "enabled": True,
                    "priority": 100,
                }
            ]
        },
    )
    assert bound_skills.status_code == 200, bound_skills.text

    space = client.post(
        "/api/v1/knowledge-spaces",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "code": "finance_refund_knowledge",
            "name": "退款财务知识",
            "description": "退款单与审批规则",
            "domain": "finance",
            "owner_id": "draft-admin",
        },
    )
    assert space.status_code == 201, space.text
    bound_knowledge = client.put(
        f"/api/v1/digital-employees/{employee_id}/knowledge-bindings",
        headers=ADMIN,
        json={
            "bindings": [
                {
                    "knowledge_space_id": space.json()["id"],
                    "enabled": True,
                }
            ]
        },
    )
    assert bound_knowledge.status_code == 200, bound_knowledge.text

    passed_evaluation = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/evaluate",
        headers=ADMIN,
    )
    assert passed_evaluation.status_code == 200
    assert passed_evaluation.json()["status"] == "EVALUATION_PASSED"
    assert passed_evaluation.json()["evaluation"]["passed"] is True
    assert passed_evaluation.json()["evaluation"]["resource_hash"]

    removed_knowledge = client.put(
        f"/api/v1/digital-employees/{employee_id}/knowledge-bindings",
        headers=ADMIN,
        json={"bindings": []},
    )
    assert removed_knowledge.status_code == 200
    stale_publish = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/publish",
        headers=ADMIN,
    )
    assert stale_publish.status_code == 409
    assert (
        stale_publish.json()["code"]
        == "EMPLOYEE_DRAFT_RESOURCES_CHANGED"
    )
    restored_knowledge = client.put(
        f"/api/v1/digital-employees/{employee_id}/knowledge-bindings",
        headers=ADMIN,
        json={
            "bindings": [
                {
                    "knowledge_space_id": space.json()["id"],
                    "enabled": True,
                }
            ]
        },
    )
    assert restored_knowledge.status_code == 200

    published = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/publish",
        headers=ADMIN,
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "PUBLISHED"
    published_employee = client.get(
        "/api/v1/digital-employees?business_unit_id=bu_demo",
        headers=AGENT,
    ).json()
    assert next(
        employee
        for employee in published_employee
        if employee["id"] == employee_id
    )["status"] == "ACTIVE"
    duplicate_publish = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/publish",
        headers=ADMIN,
    )
    assert duplicate_publish.status_code == 409
    assert (
        duplicate_publish.json()["code"]
        == "EMPLOYEE_DRAFT_ALREADY_PUBLISHED"
    )

    revisions = client.get(
        f"/api/v1/digital-employees/{employee_id}/revisions",
        headers=AGENT,
    ).json()
    assert {"TRIAL", "PUBLISHED"}.issubset(
        {revision["status"] for revision in revisions}
    )

    promoted = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/promote-template",
        headers=ADMIN,
    )
    assert promoted.status_code == 201, promoted.text
    managed_template = promoted.json()
    assert managed_template["status"] == "DRAFT"
    assert managed_template["builtin"] is False
    assert managed_template["source_draft_id"] == draft["id"]
    assert len(managed_template["skill_codes"]) == 1
    assert len(managed_template["knowledge_bindings"]) == 1
    promotion_revisions = client.get(
        f"/api/v1/digital-employee-drafts/{draft['id']}/revisions",
        headers=AGENT,
    ).json()
    assert promotion_revisions[0]["snapshot"]["promoted_template_id"] == (
        managed_template["id"]
    )
    assert "Promoted to template" in promotion_revisions[0]["change_note"]

    duplicate_promotion = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/promote-template",
        headers=ADMIN,
    )
    assert duplicate_promotion.status_code == 409
    assert (
        duplicate_promotion.json()["code"]
        == "EMPLOYEE_DRAFT_TEMPLATE_EXISTS"
    )

    approved_template = client.post(
        f"/api/v1/digital-employee-templates/"
        f"{managed_template['id']}/review",
        headers=ADMIN,
        json={"decision": "APPROVE", "note": "模板配置已复核"},
    )
    assert approved_template.status_code == 200
    assert approved_template.json()["status"] == "APPROVED"

    published_template = client.post(
        f"/api/v1/digital-employee-templates/"
        f"{managed_template['id']}/publish",
        headers=ADMIN,
    )
    assert published_template.status_code == 200
    assert published_template.json()["status"] == "PUBLISHED"

    published_templates = client.get(
        "/api/v1/digital-employee-templates?business_unit_id=bu_demo",
        headers=AGENT,
    ).json()
    assert any(
        template["code"] == managed_template["code"]
        and template["builtin"] is False
        for template in published_templates
    )

    extra_space = client.post(
        "/api/v1/knowledge-spaces",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "code": "clone_extra_knowledge",
            "name": "克隆附加知识",
            "description": "验证模板知识合并",
            "domain": "finance",
            "owner_id": "draft-admin",
        },
    )
    assert extra_space.status_code == 201, extra_space.text

    cloned = client.post(
        "/api/v1/digital-employees/from-template",
        headers=ADMIN,
        json={
            "name": "模板复制财务专员",
            "template_code": managed_template["code"],
            "business_unit_id": "bu_demo",
            "knowledge_space_ids": [extra_space.json()["id"]],
        },
    )
    assert cloned.status_code == 201, cloned.text
    cloned_employee = cloned.json()
    assert cloned_employee["status"] == "TRIAL"
    assert (
        cloned_employee["manifest"]["template_id"]
        == managed_template["id"]
    )
    assert (
        cloned_employee["manifest"]["template_version"]
        == published_template.json()["version"]
    )
    assert (
        cloned_employee["manifest"]["activation_required"] is True
    )
    cloned_skills = client.get(
        f"/api/v1/digital-employees/{cloned_employee['id']}/skills",
        headers=AGENT,
    ).json()
    cloned_knowledge = client.get(
        f"/api/v1/digital-employees/"
        f"{cloned_employee['id']}/knowledge-bindings",
        headers=AGENT,
    ).json()
    assert len(cloned_skills) == 1
    assert len(cloned_knowledge) == 2
    required_knowledge_id = managed_template[
        "knowledge_bindings"
    ][0]["knowledge_space_id"]
    missing_required = client.put(
        f"/api/v1/digital-employees/"
        f"{cloned_employee['id']}/knowledge-bindings",
        headers=ADMIN,
        json={
            "bindings": [
                {
                    "knowledge_space_id": extra_space.json()["id"],
                    "enabled": True,
                }
            ]
        },
    )
    assert missing_required.status_code == 200
    failed_clone_activation = client.post(
        f"/api/v1/digital-employees/{cloned_employee['id']}/activate",
        headers=ADMIN,
    )
    assert failed_clone_activation.status_code == 200
    assert (
        failed_clone_activation.json()["status"]
        == "EVALUATION_FAILED"
    )
    failed_checks = {
        check["key"]: check
        for check in failed_clone_activation.json()[
            "activation_evaluation"
        ]["checks"]
    }
    assert failed_checks["knowledge"]["status"] == "FAILED"
    restored = client.put(
        f"/api/v1/digital-employees/"
        f"{cloned_employee['id']}/knowledge-bindings",
        headers=ADMIN,
        json={
            "bindings": [
                {
                    "knowledge_space_id": required_knowledge_id,
                    "enabled": True,
                },
                {
                    "knowledge_space_id": extra_space.json()["id"],
                    "enabled": True,
                },
            ]
        },
    )
    assert restored.status_code == 200
    activated_clone = client.post(
        f"/api/v1/digital-employees/{cloned_employee['id']}/activate",
        headers=ADMIN,
    )
    assert activated_clone.status_code == 200, activated_clone.text
    assert activated_clone.json()["status"] == "ACTIVE"
    assert activated_clone.json()["activation_evaluation"]["passed"] is True

    rolled_back_template = client.post(
        f"/api/v1/digital-employee-templates/"
        f"{managed_template['id']}/rollback",
        headers=ADMIN,
    )
    assert rolled_back_template.status_code == 200
    assert rolled_back_template.json()["status"] == "DISABLED"
    blocked_clone = client.post(
        "/api/v1/digital-employees/from-template",
        headers=ADMIN,
        json={
            "name": "停用模板复制失败",
            "template_code": managed_template["code"],
            "business_unit_id": "bu_demo",
        },
    )
    assert blocked_clone.status_code == 404

    reopened_template = client.post(
        f"/api/v1/digital-employee-templates/"
        f"{managed_template['id']}/reopen",
        headers=ADMIN,
    )
    assert reopened_template.status_code == 200
    assert reopened_template.json()["status"] == "DRAFT"
    edited_template = client.post(
        f"/api/v1/digital-employee-templates/"
        f"{managed_template['id']}/edit",
        headers=ADMIN,
        json={
            "name": "退款财务专员模板 v2",
            "capabilities": ["退款单审核", "财务审批协同", "对账"],
            "skill_codes": ["ecommerce-aftersales"],
            "tool_allowlist": ["ticket.read", "knowledge.search"],
        },
    )
    assert edited_template.status_code == 200, edited_template.text
    assert edited_template.json()["status"] == "DRAFT"
    assert edited_template.json()["name"] == "退款财务专员模板 v2"
    missing_template_reason = client.post(
        f"/api/v1/digital-employee-templates/"
        f"{managed_template['id']}/review",
        headers=ADMIN,
        json={"decision": "REJECT", "note": ""},
    )
    assert missing_template_reason.status_code == 422
    assert (
        missing_template_reason.json()["code"]
        == "EMPLOYEE_TEMPLATE_REJECTION_REASON_REQUIRED"
    )
    template_revisions = client.get(
        f"/api/v1/digital-employee-templates/"
        f"{managed_template['id']}/revisions",
        headers=AGENT,
    ).json()
    assert {
        "DRAFT",
        "APPROVED",
        "PUBLISHED",
        "DISABLED",
    }.issubset(
        {revision["status"] for revision in template_revisions}
    )
    assert len(template_revisions) >= 6

    rolled_back = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/rollback",
        headers=ADMIN,
    )
    assert rolled_back.status_code == 200, rolled_back.text
    assert rolled_back.json()["status"] == "ROLLED_BACK"
    final_employees = client.get(
        "/api/v1/digital-employees?business_unit_id=bu_demo",
        headers=AGENT,
    ).json()
    assert next(
        employee
        for employee in final_employees
        if employee["id"] == employee_id
    )["status"] == "DISABLED"
    revisions = client.get(
        f"/api/v1/digital-employees/{employee_id}/revisions",
        headers=AGENT,
    ).json()
    assert "ROLLED_BACK" in {
        revision["status"] for revision in revisions
    }
    duplicate_rollback = client.post(
        f"/api/v1/digital-employee-drafts/{draft['id']}/rollback",
        headers=ADMIN,
    )
    assert duplicate_rollback.status_code == 409
    assert duplicate_rollback.json()["code"] == "EMPLOYEE_DRAFT_NOT_PUBLISHED"

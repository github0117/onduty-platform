from fastapi.testclient import TestClient

ADMIN = {"X-Actor-Id": "workforce-admin", "X-Actor-Role": "admin"}
AGENT = {"X-Actor-Id": "workforce-agent", "X-Actor-Role": "agent"}


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


def test_supervisor_plans_cross_employee_tasks(
    client: TestClient,
) -> None:
    supervisor = _create_template(
        client,
        "customer_service_supervisor",
        "客服协调主管",
    )
    aftersales = _create_template(
        client,
        "ecommerce_aftersales",
        "售后专家",
    )
    logistics = _create_template(
        client,
        "ecommerce_logistics",
        "物流专家",
    )

    created = client.post(
        "/api/v1/workforce/tasks",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "title": "退款与物流联合处理",
            "objective": (
                "买家反馈商品破损，正在申请退款，同时物流三天没有更新。"
                "需要协调售后和物流专家，并检查审批风险。"
            ),
            "context": {"order_id": "PDD-1001"},
        },
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["status"] == "PLAN_READY"
    assert task["supervisor_employee_id"] == supervisor["id"]
    assert task["supervisor_employee_name"] == "客服协调主管"
    assert len(task["steps"]) == 4
    assert task["capability_gaps"] == []
    assert task["capability_assessed_at"] is not None
    readiness = {
        item["employee_name"]: item
        for item in task["employee_readiness"]
    }
    assert readiness["物流专家"]["status"] == "DEGRADED"
    logistics_checks = {
        item["key"]: item
        for item in readiness["物流专家"]["checks"]
    }
    assert logistics_checks["knowledge"]["status"] == "WARNING"
    assert logistics_checks["mcp"]["status"] == "WARNING"
    assert logistics_checks["skills"]["status"] == "READY"
    assigned_ids = {
        step["assigned_employee_id"] for step in task["steps"]
    }
    assert aftersales["id"] in assigned_ids or logistics["id"] in assigned_ids
    fact_step = next(
        step for step in task["steps"] if step["title"] == "查询专业事实"
    )
    assert fact_step["assigned_employee_id"] == logistics["id"]
    assert (
        fact_step["required_capability"]
        == "实时物流与订单事实核验"
    )
    assert fact_step["route_reason_code"] in {
        "INTENT_MATCH",
        "SEMANTIC_MATCH",
    }
    assert fact_step["route_reason"]
    assert fact_step["route_confidence"] is not None
    assert any(
        candidate["employee_id"] == logistics["id"]
        and candidate["selected"] is True
        and candidate["score"] > 0
        for candidate in fact_step["route_candidates"]
    )
    assert all(
        step["required_capability"] and step["route_reason"]
        for step in task["steps"]
    )
    assert all(step["status"] == "PENDING" for step in task["steps"])
    assert all(step["assigned_employee_name"] for step in task["steps"])

    listing = client.get(
        "/api/v1/workforce/tasks?business_unit_id=bu_demo",
        headers=AGENT,
    )
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    detail = client.get(
        f"/api/v1/workforce/tasks/{task['id']}",
        headers=AGENT,
    )
    assert detail.status_code == 200
    assert detail.json()["id"] == task["id"]

    executed = client.post(
        f"/api/v1/workforce/tasks/{task['id']}/execute",
        headers=AGENT,
    )
    assert executed.status_code == 200, executed.text
    completed = client.get(
        f"/api/v1/workforce/tasks/{task['id']}",
        headers=AGENT,
    ).json()
    assert completed["status"] in {"COMPLETED", "NEEDS_REVIEW"}
    assert all(
        step["status"] == "SUCCEEDED" for step in completed["steps"]
    )
    assert all(
        step["output"]["summary"] for step in completed["steps"]
    )
    assert completed["result_summary"]


def test_supervisor_plans_hr_task(client: TestClient) -> None:
    _create_template(
        client,
        "customer_service_supervisor",
        "任务主管",
    )
    hr = _create_template(
        client,
        "hr_onboarding",
        "HR 入职专员",
    )
    created = client.post(
        "/api/v1/workforce/tasks",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "title": "新员工入职资料准备",
            "objective": "协助新员工完成入职资料收集和劳动合同材料检查。",
        },
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert [step["title"] for step in task["steps"]] == [
        "确认入职资料要求",
        "检查缺失与合规",
        "生成入职沟通草案",
    ]
    assert task["capability_gaps"] == []
    assert task["capability_assessed_at"] is not None
    assessed_at = task["capability_assessed_at"]
    readiness = task["employee_readiness"]
    assert len(readiness) == 1
    assert readiness[0]["status"] == "DEGRADED"
    checks = {
        item["key"]: item
        for item in readiness[0]["checks"]
    }
    assert checks["knowledge"]["status"] == "WARNING"
    assert checks["skills"]["status"] == "READY"
    assert checks["mcp"]["status"] == "NOT_APPLICABLE"
    assert all(
        step["assigned_employee_id"] == hr["id"] for step in task["steps"]
    ), task["steps"]

    disabled = client.patch(
        f"/api/v1/digital-employees/{hr['id']}",
        headers=ADMIN,
        json={"status": "DISABLED"},
    )
    assert disabled.status_code == 200, disabled.text
    snapshot = client.get(
        f"/api/v1/workforce/tasks/{task['id']}",
        headers=AGENT,
    ).json()
    assert snapshot["capability_assessed_at"] == assessed_at
    assert snapshot["employee_readiness"] == readiness


def test_supervisor_reports_missing_employee_capability(
    client: TestClient,
) -> None:
    _create_template(
        client,
        "customer_service_supervisor",
        "任务主管",
    )

    created = client.post(
        "/api/v1/workforce/tasks",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "title": "新员工入职资料准备",
            "objective": "协助新员工完成入职资料收集和劳动合同材料检查。",
        },
    )

    assert created.status_code == 201, created.text
    task = created.json()
    assert len(task["capability_gaps"]) == 3
    assert all(
        gap["status"] == "DRAFT_ONLY"
        and gap["approval_required"] is True
        and gap["recommended_template_code"] == "hr_onboarding"
        and gap["recommended_template_name"] == "HR 入职专员"
        for gap in task["capability_gaps"]
    )
    assert all(
        gap["reason"] for gap in task["capability_gaps"]
    )
    executed = client.post(
        f"/api/v1/workforce/tasks/{task['id']}/execute",
        headers=AGENT,
    )
    assert executed.status_code == 409
    assert executed.json()["code"] == "WORKFORCE_CAPABILITY_GAP"


def test_supervisor_parses_explicit_finance_and_warehouse_gaps(
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
    objective = """
客户投诉订单已经签收，但商品破损且少件，要求退款并补发。

【需要的专业能力（供主管员工拆解分配）】

客服沟通能力：起草安抚话术，向客户同步处理进度。
售后审核能力：核实订单、破损照片和退款标准。
仓储物流能力：查询库存、安排补发并联系快递拦截。
财务处理能力：生成退款单，并走加急审批流。
"""

    created = client.post(
        "/api/v1/workforce/tasks",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "title": "订单异常的退款与补发联合处理",
            "objective": objective,
            "context": {"order_id": "ORD-1001"},
        },
    )

    assert created.status_code == 201, created.text
    task = created.json()
    assert [step["title"] for step in task["steps"]] == [
        "识别客户主诉与关联业务",
        "查询专业事实",
        "生成统一处理建议",
        "检查风险与审批",
    ]
    missing = {
        gap["required_capability"]: gap
        for gap in task["capability_gaps"]
    }
    assert {
        "仓储物流能力",
        "财务处理能力",
    }.issubset(missing)
    assert all(
        missing[label]["step_id"] is None
        and missing[label]["recommended_template_code"] is None
        and missing[label]["status"] == "DRAFT_ONLY"
        for label in ("仓储物流能力", "财务处理能力")
    )

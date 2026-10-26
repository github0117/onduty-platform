from typing import Any

from fastapi.testclient import TestClient

ADMIN = {"X-Actor-Id": "routing-admin", "X-Actor-Role": "admin"}
AGENT = {"X-Actor-Id": "routing-agent", "X-Actor-Role": "agent"}


def _create_from_template(
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


def _create_manual_employee(
    client: TestClient,
    *,
    employee_key: str,
    name: str,
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json={
            "employee_key": employee_key,
            "name": name,
            "version": "1.0.0",
            "scenario_type": "customer_service_ticket",
            "workflow_key": "customer_service_ticket_v1",
            "business_unit_id": "bu_demo",
            "service_identity": f"digital_employee.{employee_key}",
            "handoff_queue": "MANUAL_TRIAGE",
            "tool_allowlist": [
                "ticket.read",
                "knowledge.search",
                "draft.create",
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_ticket(
    client: TestClient,
    *,
    external_id: str,
    subject: str,
    body: str,
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/tickets",
        headers={**AGENT, "Idempotency-Key": f"routing:{external_id}"},
        json={
            "business_unit_id": "bu_demo",
            "source": {
                "system": "routing_test",
                "channel": "web_form",
                "external_ticket_id": external_id,
            },
            "requester": {
                "external_ref": "routing-buyer",
                "customer_tier": "standard",
            },
            "subject": subject,
            "body": body,
            "locale": "zh-CN",
            "attachments": [],
            "metadata": {},
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def _decision_for_ticket(
    client: TestClient,
    ticket_id: str,
) -> dict[str, Any]:
    response = client.get(
        "/api/v1/digital-employee-route-decisions?business_unit_id=bu_demo",
        headers=AGENT,
    )
    assert response.status_code == 200, response.text
    return next(
        item
        for item in response.json()["items"]
        if item["ticket_id"] == ticket_id
    )


def test_keyword_synonym_and_semantic_routes_explain_candidates(
    client: TestClient,
) -> None:
    presales = _create_from_template(
        client,
        template_code="ecommerce_presales",
        name="参数顾问",
    )
    aftersales = _create_from_template(
        client,
        template_code="ecommerce_aftersales",
        name="售后顾问",
    )
    logistics = _create_from_template(
        client,
        template_code="ecommerce_logistics",
        name="物流顾问",
    )

    presales_ticket = _create_ticket(
        client,
        external_id="ROUTE-EXPLAIN-PRESALES",
        subject="杯子的容量和颜色",
        body="请介绍这款杯子的容量、颜色和材质。",
    )
    damage_ticket = _create_ticket(
        client,
        external_id="ROUTE-EXPLAIN-DAMAGE",
        subject="商品漏水",
        body="收到的杯子漏水，需要处理。",
    )
    logistics_ticket = _create_ticket(
        client,
        external_id="ROUTE-EXPLAIN-LOGISTICS",
        subject="包裹到哪了",
        body="快递一直没有更新，请查一下。",
    )

    for ticket, employee in (
        (presales_ticket, presales),
        (damage_ticket, aftersales),
        (logistics_ticket, logistics),
    ):
        assert ticket["employee_id"] == employee["id"]
        decision = _decision_for_ticket(client, ticket["id"])
        assert decision["reason_code"] == "INTENT_MATCH"
        assert decision["reason"]
        assert decision["score"] > 0
        assert 0 <= decision["confidence"] <= 1
        assert any(
            candidate["employee_id"] == employee["id"]
            and candidate["selected"] is True
            and candidate["matched_intents"]
            for candidate in decision["candidates"]
        )
        assert all(
            {
                "eligible",
                "excluded_reasons",
                "keyword_score",
                "semantic_score",
                "matched_subject_terms",
                "matched_body_terms",
                "matched_synonyms",
            }.issubset(candidate)
            for candidate in decision["candidates"]
        )


def test_enterprise_template_routes_internal_service_requests(
    client: TestClient,
) -> None:
    enterprise = _create_from_template(
        client,
        template_code="enterprise_service_desk",
        name="内部服务台",
    )
    requests = [
        ("报销流程", "公司报销流程是什么？", "报销"),
        ("VPN 连不上", "办公室 VPN 连不上，影响远程访问。", "VPN"),
        ("办公用品申领", "怎么申领办公用品？", "办公用品"),
        ("财务系统权限", "申请开通财务系统权限。", "财务"),
        ("会议室预订", "怎么预订会议室？", "会议室"),
    ]

    for index, (subject, body, term) in enumerate(requests):
        ticket = _create_ticket(
            client,
            external_id=f"ROUTE-ENTERPRISE-{index}",
            subject=subject,
            body=body,
        )
        assert ticket["employee_id"] == enterprise["id"]
        decision = _decision_for_ticket(client, ticket["id"])
        assert decision["reason_code"] == "INTENT_MATCH"
        selected = next(
            candidate
            for candidate in decision["candidates"]
            if candidate["selected"]
        )
        assert term in selected["matched_intents"]


def test_negated_refund_does_not_override_logistics(
    client: TestClient,
) -> None:
    _create_from_template(
        client,
        template_code="ecommerce_aftersales",
        name="售后顾问",
    )
    logistics = _create_from_template(
        client,
        template_code="ecommerce_logistics",
        name="物流顾问",
    )
    ticket = _create_ticket(
        client,
        external_id="ROUTE-NEGATION",
        subject="不要退款，只问物流",
        body="我没有申请退款，只想知道快递到哪了。",
    )

    assert ticket["employee_id"] == logistics["id"]
    decision = _decision_for_ticket(client, ticket["id"])
    assert decision["reason_code"] == "INTENT_MATCH"
    aftersales_candidate = next(
        candidate
        for candidate in decision["candidates"]
        if candidate["employee_name"] == "售后顾问"
    )
    assert "退款" not in aftersales_candidate["matched_intents"]
    assert "退款" not in aftersales_candidate["matched_subject_terms"]
    assert "退款" not in aftersales_candidate["matched_body_terms"]


def test_negative_logistics_status_still_routes_logistics(
    client: TestClient,
) -> None:
    logistics = _create_from_template(
        client,
        template_code="ecommerce_logistics",
        name="异常物流顾问",
    )
    ticket = _create_ticket(
        client,
        external_id="ROUTE-NEGATIVE-STATUS",
        subject="包裹未签收",
        body="物流轨迹显示一直没有签收，请帮忙查询。",
    )

    assert ticket["employee_id"] == logistics["id"]
    decision = _decision_for_ticket(client, ticket["id"])
    assert decision["reason_code"] == "INTENT_MATCH"
    selected = next(
        candidate
        for candidate in decision["candidates"]
        if candidate["selected"]
    )
    assert selected["matched_intents"]


def test_close_candidates_require_human_confirmation(
    client: TestClient,
) -> None:
    first = _create_from_template(
        client,
        template_code="ecommerce_presales",
        name="参数顾问甲",
    )
    second = _create_from_template(
        client,
        template_code="ecommerce_presales",
        name="参数顾问乙",
    )
    ticket = _create_ticket(
        client,
        external_id="ROUTE-AMBIGUOUS",
        subject="容量和颜色",
        body="请说明容量、颜色和材质。",
    )

    assert ticket["employee_id"] in {first["id"], second["id"]}
    decision = _decision_for_ticket(client, ticket["id"])
    assert decision["reason_code"] == "AMBIGUOUS_REQUIRES_HUMAN"
    assert "人工确认" in decision["reason"]
    selected = [
        candidate
        for candidate in decision["candidates"]
        if candidate["selected"]
    ]
    assert len(selected) == 1
    tied = [
        candidate
        for candidate in decision["candidates"]
        if candidate["employee_id"] in {first["id"], second["id"]}
    ]
    assert len(tied) == 2
    assert abs(float(tied[0]["score"]) - float(tied[1]["score"])) < 0.06


def test_ineligible_candidates_include_exclusion_reasons(
    client: TestClient,
) -> None:
    aftersales = _create_from_template(
        client,
        template_code="ecommerce_aftersales",
        name="停用售后顾问",
    )
    logistics = _create_from_template(
        client,
        template_code="ecommerce_logistics",
        name="渠道受限物流顾问",
    )
    fallback = _create_manual_employee(
        client,
        employee_key="routing_fallback",
        name="人工兜底客服",
    )
    disabled = client.patch(
        f"/api/v1/digital-employees/{aftersales['id']}",
        headers=ADMIN,
        json={"status": "DISABLED"},
    )
    assert disabled.status_code == 200, disabled.text
    rule = client.get(
        f"/api/v1/digital-employees/{logistics['id']}/route-rule",
        headers=AGENT,
    ).json()
    updated = client.put(
        f"/api/v1/digital-employees/{logistics['id']}/route-rule",
        headers=ADMIN,
        json={
            "intents": rule["intents"],
            "categories": rule["categories"],
            "channels": ["email"],
            "priority": rule["priority"],
            "fallback": False,
            "enabled": True,
        },
    )
    assert updated.status_code == 200, updated.text
    ticket = _create_ticket(
        client,
        external_id="ROUTE-EXCLUSIONS",
        subject="商品破损并查询物流",
        body="商品破损需要处理，同时请查询快递。",
    )

    assert ticket["employee_id"] == fallback["id"]
    decision = _decision_for_ticket(client, ticket["id"])
    candidates = {
        candidate["employee_id"]: candidate
        for candidate in decision["candidates"]
    }
    assert candidates[aftersales["id"]]["eligible"] is False
    assert any(
        "员工状态" in reason
        for reason in candidates[aftersales["id"]]["excluded_reasons"]
    )
    assert candidates[logistics["id"]]["eligible"] is False
    assert any(
        "渠道" in reason
        for reason in candidates[logistics["id"]]["excluded_reasons"]
    )
    assert candidates[fallback["id"]]["selected"] is True
    assert decision["reason_code"] == "LOW_CONFIDENCE_FALLBACK"


def test_semantic_only_match_has_explicit_reason(
    client: TestClient,
) -> None:
    employee = _create_manual_employee(
        client,
        employee_key="invoice_verification",
        name="票据核验专员",
    )
    updated = client.put(
        f"/api/v1/digital-employees/{employee['id']}/route-rule",
        headers=ADMIN,
        json={
            "intents": ["发票验真"],
            "categories": [],
            "channels": [],
            "priority": 50,
            "fallback": False,
            "enabled": True,
        },
    )
    assert updated.status_code == 200, updated.text
    ticket = _create_ticket(
        client,
        external_id="ROUTE-SEMANTIC",
        subject="发票真假校验",
        body="请判断这张发票是否为真实票据。",
    )

    assert ticket["employee_id"] == employee["id"]
    decision = _decision_for_ticket(client, ticket["id"])
    assert decision["reason_code"] == "SEMANTIC_MATCH"
    selected = next(
        candidate
        for candidate in decision["candidates"]
        if candidate["selected"]
    )
    assert selected["keyword_score"] == 0
    assert selected["semantic_score"] >= 0.28

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient

from ticket_agent.ecommerce.models import EcommerceProduct
from ticket_agent.knowledge.service import KnowledgeService
from ticket_agent.shared.db import SessionLocal
from ticket_agent.workers.celery_app import celery_app
from ticket_agent.workers.tasks import ingest_knowledge_version_task

ADMIN_HEADERS = {
    "X-Actor-Id": "admin-1",
    "X-Actor-Role": "admin",
}
AGENT_HEADERS = {
    "X-Actor-Id": "agent-1",
    "X-Actor-Role": "agent",
}


def _create_document(
    client: TestClient,
    *,
    title: str = "企业通知配置指南",
    scope: dict[str, object] | None = None,
    space_id: str | None = None,
) -> str:
    response = client.post(
        "/api/v1/knowledge-documents",
        headers=ADMIN_HEADERS,
        json={
            "space_id": space_id,
            "business_unit_id": "bu_demo",
            "title": title,
            "doc_type": "SOP",
            "owner_id": "admin-1",
            "scope": scope or {},
        },
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def _create_space(
    client: TestClient,
    *,
    code: str,
    name: str,
    workflow_key: str,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/knowledge-spaces",
        headers=ADMIN_HEADERS,
        json={
            "business_unit_id": "bu_demo",
            "code": code,
            "name": name,
            "description": f"{name}测试空间",
            "domain": "ecommerce",
            "channel": "pinduoduo",
            "category": "雪地靴",
            "workflow_key": workflow_key,
            "owner_id": "admin-1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_version(
    client: TestClient,
    document_id: str,
    *,
    label: str,
    content: str,
    effective_from: datetime | None = None,
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/knowledge-documents/{document_id}/versions",
        headers=ADMIN_HEADERS,
        json={
            "version_label": label,
            "content": content,
            "effective_from": (effective_from or datetime.now(UTC)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _publish(
    client: TestClient,
    document_id: str,
    version_id: str,
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/knowledge-documents/{document_id}/versions/{version_id}/publish",
        headers=ADMIN_HEADERS,
        json={"release_note": "test release"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_create_publish_and_search_knowledge(client: TestClient) -> None:
    document_id = _create_document(client)
    version = _create_version(
        client,
        document_id,
        label="1.0",
        content=(
            "企业通知配置指南。管理员进入后台设置页面，打开消息通知，"
            "然后为团队选择需要启用的通知渠道。"
        ),
    )
    published = _publish(client, document_id, str(version["id"]))

    search = client.post(
        "/api/v1/knowledge/search",
        headers=AGENT_HEADERS,
        json={
            "query": "如何给团队配置消息通知",
            "business_unit_id": "bu_demo",
            "top_k": 3,
        },
    )

    assert published["status"] == "ACTIVE"
    assert version["chunk_count"] > 0
    assert search.status_code == 200
    assert search.json()["items"]
    assert search.json()["items"][0]["title"] == "企业通知配置指南"


def test_list_knowledge_versions(client: TestClient) -> None:
    document_id = _create_document(client)
    _create_version(
        client,
        document_id,
        label="1.0",
        content="企业通知配置指南第一版。",
    )
    _create_version(
        client,
        document_id,
        label="2.0",
        content="企业通知配置指南第二版。",
    )

    response = client.get(
        f"/api/v1/knowledge-documents/{document_id}/versions",
        headers=AGENT_HEADERS,
    )

    assert response.status_code == 200
    assert {item["version_label"] for item in response.json()} == {"1.0", "2.0"}
    assert all(item["status"] == "DRAFT" for item in response.json())


def test_update_and_archive_knowledge_document(client: TestClient) -> None:
    document_id = _create_document(client)
    version = _create_version(
        client,
        document_id,
        label="archive-1.0",
        content="团队消息通知在设置中心完成配置。",
    )
    _publish(client, document_id, str(version["id"]))
    updated = client.patch(
        f"/api/v1/knowledge-documents/{document_id}",
        headers=ADMIN_HEADERS,
        json={
            "title": "企业通知配置指南（新版）",
            "scope": {"products": ["admin_portal"], "regions": ["cn-east"]},
        },
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "企业通知配置指南（新版）"
    assert updated.json()["scope"]["regions"] == ["cn-east"]

    archived = client.post(
        f"/api/v1/knowledge-documents/{document_id}/archive",
        headers=ADMIN_HEADERS,
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "ARCHIVED"
    versions = client.get(
        f"/api/v1/knowledge-documents/{document_id}/versions",
        headers=AGENT_HEADERS,
    ).json()
    assert versions[0]["status"] == "RETIRED"
    search = client.post(
        "/api/v1/knowledge/search",
        headers=AGENT_HEADERS,
        json={
            "query": "团队消息通知如何配置",
            "business_unit_id": "bu_demo",
            "scope": {"products": "admin_portal", "regions": "cn-east"},
        },
    )
    assert search.json()["items"] == []
    restored = client.post(
        f"/api/v1/knowledge-documents/{document_id}/restore",
        headers=ADMIN_HEADERS,
    )
    assert restored.status_code == 200
    assert restored.json()["status"] == "ACTIVE"
    restored_versions = client.get(
        f"/api/v1/knowledge-documents/{document_id}/versions",
        headers=AGENT_HEADERS,
    ).json()
    assert restored_versions[0]["status"] == "ACTIVE"
    restored_search = client.post(
        "/api/v1/knowledge/search",
        headers=AGENT_HEADERS,
        json={
            "query": "团队消息通知如何配置",
            "business_unit_id": "bu_demo",
            "scope": {"products": "admin_portal", "regions": "cn-east"},
        },
    )
    assert restored_search.status_code == 200
    assert restored_search.json()["items"]


def test_future_version_does_not_replace_current_version(
    client: TestClient,
) -> None:
    document_id = _create_document(client)
    current = _create_version(
        client,
        document_id,
        label="1.0",
        content="企业通知配置指南。管理员在设置中心配置团队消息通知。",
    )
    _publish(client, document_id, str(current["id"]))

    future = _create_version(
        client,
        document_id,
        label="2.0",
        content="未来版本：企业通知将在新的管理中心配置，不再使用旧设置页。",
        effective_from=datetime.now(UTC) + timedelta(days=1),
    )
    _publish(client, document_id, str(future["id"]))

    search = client.post(
        "/api/v1/knowledge/search",
        headers=AGENT_HEADERS,
        json={
            "query": "企业通知在哪里配置",
            "business_unit_id": "bu_demo",
        },
    )

    assert search.json()["items"]
    assert {item["version"] for item in search.json()["items"]} == {"1.0"}


def test_ticket_draft_contains_knowledge_citation(client: TestClient) -> None:
    document_id = _create_document(client)
    version = _create_version(
        client,
        document_id,
        label="1.0",
        content=(
            "企业通知配置指南。管理员进入后台设置，打开消息通知，"
            "选择团队范围并保存配置。"
        ),
    )
    _publish(client, document_id, str(version["id"]))

    created = client.post(
        "/api/v1/tickets",
        headers={
            **AGENT_HEADERS,
            "Idempotency-Key": "knowledge-ticket:001",
        },
        json={
            "business_unit_id": "bu_demo",
            "source": {
                "system": "demo_helpdesk",
                "channel": "web_form",
                "external_ticket_id": "KNOWLEDGE-TICKET-001",
            },
            "requester": {
                "external_ref": "customer-1",
                "customer_tier": "standard",
            },
            "subject": "如何给团队配置消息通知",
            "body": "管理员应该如何配置企业通知？",
            "locale": "zh-CN",
            "attachments": [],
            "metadata": {},
        },
    )
    ticket_id = created.json()["id"]
    detail = client.get(
        f"/api/v1/tickets/{ticket_id}",
        headers=AGENT_HEADERS,
    ).json()

    assert detail["draft"]["citations"]
    assert detail["draft"]["citations"][0]["title"] == "企业通知配置指南"
    assert detail["draft"]["citations"][0]["version"] == "1.0"
    assert detail["draft"]["generator_provider"] == "local"
    assert detail["draft"]["grounding_status"] == "GROUNDED"
    assert detail["draft"]["claims"]


def test_non_admin_cannot_publish_knowledge(client: TestClient) -> None:
    response = client.post(
        "/api/v1/knowledge-documents",
        headers=AGENT_HEADERS,
        json={
            "business_unit_id": "bu_demo",
            "title": "未授权文档",
            "doc_type": "FAQ",
            "owner_id": "agent-1",
            "scope": {},
        },
    )

    assert response.status_code == 403


def test_create_knowledge_version_from_markdown_file(client: TestClient) -> None:
    document_id = _create_document(client)
    response = client.post(
        f"/api/v1/knowledge-documents/{document_id}/versions/from-file",
        params={"version_label": "file-1.0", "filename": "guide.md"},
        headers={
            **ADMIN_HEADERS,
            "Content-Type": "text/markdown",
        },
        content="# 企业通知\n管理员在设置中心为团队配置消息通知。",
    )

    assert response.status_code == 201, response.text
    version = response.json()
    assert version["source_filename"] == "guide.md"
    assert version["parser_name"] == "plain-text"
    assert version["chunk_count"] > 0


def test_async_upload_stores_source_and_ingests_inline(
    client: TestClient,
) -> None:
    document_id = _create_document(client)
    upload = client.post(
        f"/api/v1/knowledge-documents/{document_id}/uploads",
        params={"version_label": "async-1.0", "filename": "async-guide.md"},
        headers={
            **ADMIN_HEADERS,
            "Content-Type": "text/markdown",
        },
        content="# Async guide\nConfigure team notifications in settings.",
    )

    assert upload.status_code == 202, upload.text
    accepted = upload.json()
    assert accepted["status"] == "PROCESSING"
    assert accepted["source_object_key"].endswith("/async-guide.md")

    version = client.get(
        (
            f"/api/v1/knowledge-documents/{document_id}/versions/"
            f"{accepted['version_id']}"
        ),
        headers=AGENT_HEADERS,
    )
    assert version.status_code == 200
    body = version.json()
    assert body["status"] == "DRAFT"
    assert body["chunk_count"] > 0
    assert body["parser_name"] == "plain-text"
    assert body["ingestion_error"] is None


def test_knowledge_ingestion_celery_task_executes(client: TestClient) -> None:
    document_id = UUID(_create_document(client))
    with SessionLocal() as session:
        service = KnowledgeService(session)
        version, _ = service.create_async_upload(
            document_id,
            version_label="celery-eager",
            filename="celery-guide.md",
            content_type="text/markdown",
            data=b"# Guide\nConfigure notifications in settings.",
            correlation_id="celery-eager-test",
        )
        version_id = version.id

    previous_mode = celery_app.conf.task_always_eager
    celery_app.conf.task_always_eager = True
    try:
        result = ingest_knowledge_version_task.apply(
            args=[str(version_id), "celery-eager-test", "unused-outbox-event"],
            throw=True,
        )
        assert result.successful()
    finally:
        celery_app.conf.task_always_eager = previous_mode

    with SessionLocal() as session:
        version = KnowledgeService(session).get_version(document_id, version_id)
        assert version.status == "DRAFT"
        assert version.parser_name == "plain-text"


def test_search_filters_by_knowledge_scope(client: TestClient) -> None:
    admin_doc = _create_document(
        client,
        title="管理后台通知指南",
        scope={"products": ["admin_portal"]},
    )
    crm_doc = _create_document(
        client,
        title="CRM 通知指南",
        scope={"products": ["crm"]},
    )
    for document_id, label in ((admin_doc, "admin"), (crm_doc, "crm")):
        version = _create_version(
            client,
            document_id,
            label=label,
            content="团队消息通知在设置中心完成配置。",
        )
        _publish(client, document_id, str(version["id"]))

    scoped = client.post(
        "/api/v1/knowledge/search",
        headers=AGENT_HEADERS,
        json={
            "query": "团队消息通知在哪里配置",
            "business_unit_id": "bu_demo",
            "scope": {"products": "admin_portal"},
        },
    )
    unscoped = client.post(
        "/api/v1/knowledge/search",
        headers=AGENT_HEADERS,
        json={
            "query": "团队消息通知在哪里配置",
            "business_unit_id": "bu_demo",
        },
    )

    assert {item["title"] for item in scoped.json()["items"]} == {"管理后台通知指南"}
    assert unscoped.json()["items"] == []


def test_search_filters_by_dynamic_knowledge_space(client: TestClient) -> None:
    presales = _create_space(
        client,
        code="snow_boots_presales",
        name="雪地靴售前",
        workflow_key="ecommerce_customer_service_v1",
    )
    aftersales = _create_space(
        client,
        code="snow_boots_aftersales",
        name="雪地靴售后",
        workflow_key="ecommerce_customer_service_v1",
    )
    presales_doc = _create_document(
        client,
        title="售前尺码指南",
        space_id=str(presales["id"]),
        scope={
            "channel": "pinduoduo",
            "category": "雪地靴",
            "workflow": "ecommerce_customer_service_v1",
        },
    )
    aftersales_doc = _create_document(
        client,
        title="售后换码说明",
        space_id=str(aftersales["id"]),
        scope={
            "channel": "pinduoduo",
            "category": "雪地靴",
            "workflow": "ecommerce_customer_service_v1",
        },
    )
    for document_id, label, title in (
        (presales_doc, "presales-1.0", "售前尺码指南"),
        (aftersales_doc, "aftersales-1.0", "售后换码说明"),
    ):
        version = _create_version(
            client,
            document_id,
            label=label,
            content=f"{title}：雪地靴建议按平时运动鞋尺码选择。",
        )
        _publish(client, document_id, str(version["id"]))

    search = client.post(
        "/api/v1/knowledge/search",
        headers=AGENT_HEADERS,
        json={
            "query": "雪地靴尺码怎么选",
            "business_unit_id": "bu_demo",
            "space_id": presales["id"],
            "top_k": 5,
        },
    )

    assert search.status_code == 200, search.text
    assert {item["title"] for item in search.json()["items"]} == {"售前尺码指南"}
    assert all(
        item["space_id"] == presales["id"]
        for item in search.json()["items"]
    )

    moved = client.patch(
        f"/api/v1/knowledge-documents/{presales_doc}",
        headers=ADMIN_HEADERS,
        json={"space_id": aftersales["id"]},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["space_id"] == aftersales["id"]


def test_employee_can_only_search_bound_knowledge_spaces(
    client: TestClient,
) -> None:
    presales = _create_space(
        client,
        code="bound_presales",
        name="已绑定售前知识",
        workflow_key="ecommerce_customer_service_v1",
    )
    internal = _create_space(
        client,
        code="unbound_internal",
        name="未绑定内部知识",
        workflow_key="ecommerce_customer_service_v1",
    )
    allowed_document = _create_document(
        client,
        title="可访问尺码知识",
        space_id=str(presales["id"]),
        scope={
            "channel": "pinduoduo",
            "category": "雪地靴",
            "workflow": "ecommerce_customer_service_v1",
        },
    )
    blocked_document = _create_document(
        client,
        title="内部成本知识",
        space_id=str(internal["id"]),
        scope={
            "channel": "pinduoduo",
            "category": "雪地靴",
            "workflow": "ecommerce_customer_service_v1",
        },
    )
    for document_id, label, title in (
        (allowed_document, "allowed-1.0", "可访问尺码知识"),
        (blocked_document, "blocked-1.0", "内部成本知识"),
    ):
        version = _create_version(
            client,
            document_id,
            label=label,
            content=f"{title}：雪地靴建议按平时运动鞋尺码选择。",
        )
        _publish(client, document_id, str(version["id"]))

    employee = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN_HEADERS,
        json={
            "employee_key": "bound_knowledge_employee",
            "name": "售前客服数字员工",
            "version": "1.0.0",
            "scenario_type": "customer_service_ticket",
            "workflow_key": "customer_service_ticket_v1",
            "business_unit_id": "bu_demo",
            "service_identity": "digital_employee.bound_knowledge",
            "handoff_queue": "MANUAL_TRIAGE",
            "knowledge_policy": {
                "default_scope": {
                    "channel": "pinduoduo",
                    "category": "雪地靴",
                    "workflow": "ecommerce_customer_service_v1",
                }
            },
            "model_profile": {},
            "tool_allowlist": ["knowledge.search"],
        },
    )
    assert employee.status_code == 201, employee.text
    employee_id = employee.json()["id"]
    bindings = client.put(
        f"/api/v1/digital-employees/{employee_id}/knowledge-bindings",
        headers=ADMIN_HEADERS,
        json={
            "bindings": [
                {
                    "knowledge_space_id": presales["id"],
                    "workflow_key": "ecommerce_customer_service_v1",
                    "scope": {},
                    "enabled": True,
                }
            ]
        },
    )
    assert bindings.status_code == 200, bindings.text
    assert len(bindings.json()) == 1

    search = client.post(
        "/api/v1/knowledge/search",
        headers=AGENT_HEADERS,
        json={
            "query": "雪地靴尺码怎么选",
            "business_unit_id": "bu_demo",
            "employee_id": employee_id,
            "top_k": 5,
        },
    )

    assert search.status_code == 200, search.text
    assert {item["title"] for item in search.json()["items"]} == {"可访问尺码知识"}

    cleared = client.put(
        f"/api/v1/digital-employees/{employee_id}/knowledge-bindings",
        headers=ADMIN_HEADERS,
        json={"bindings": []},
    )
    assert cleared.status_code == 200
    denied = client.post(
        "/api/v1/knowledge/search",
        headers=AGENT_HEADERS,
        json={
            "query": "雪地靴尺码怎么选",
            "business_unit_id": "bu_demo",
            "employee_id": employee_id,
        },
    )
    assert denied.status_code == 200
    assert denied.json()["items"] == []


def test_product_creation_creates_and_incrementally_updates_knowledge_card(
    client: TestClient,
) -> None:
    product = client.post(
        "/api/v1/ecommerce/products",
        headers=ADMIN_HEADERS,
        json={
            "business_unit_id": "bu_demo",
            "sku": "SYNC-SNOW-001",
            "name": "自动同步雪地靴",
            "category": "雪地靴",
            "brand": "同步品牌",
            "price": 199,
            "attributes": {
                "color": "米白色",
                "upper_material": "牛剖层革",
                "stock": 20,
            },
        },
    )
    assert product.status_code == 201, product.text
    product_id = product.json()["id"]

    documents = client.get(
        "/api/v1/knowledge-documents?business_unit_id=bu_demo",
        headers=AGENT_HEADERS,
    ).json()
    synced = [
        document
        for document in documents
        if document["source_ref"] == product_id
    ]
    assert len(synced) == 1
    assert synced[0]["source_type"] == "ecommerce_product"
    assert synced[0]["sync_status"] == "SYNCED"
    assert synced[0]["status"] == "ACTIVE"

    unchanged = client.post(
        "/api/v1/knowledge/product-sync",
        headers=ADMIN_HEADERS,
        json={"business_unit_id": "bu_demo", "product_ids": [product_id]},
    )
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["unchanged"] == 1

    with SessionLocal() as session:
        stored = session.get(EcommerceProduct, UUID(product_id))
        assert stored is not None
        stored.attributes_json = {
            **stored.attributes_json,
            "lining_material": "短毛绒",
        }
        session.commit()

    changed = client.post(
        "/api/v1/knowledge/product-sync",
        headers=ADMIN_HEADERS,
        json={"business_unit_id": "bu_demo", "product_ids": [product_id]},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["synced"] == 1
    item = changed.json()["items"][0]
    assert item["changed"] is True

    versions = client.get(
        f"/api/v1/knowledge-documents/{item['document_id']}/versions",
        headers=AGENT_HEADERS,
    )
    assert versions.status_code == 200
    assert len(versions.json()) == 2


def test_knowledge_retrieval_evaluation_records_metrics_and_verdict(
    client: TestClient,
) -> None:
    space = _create_space(
        client,
        code="evaluation_presales",
        name="评测售前知识",
        workflow_key="ecommerce_customer_service_v1",
    )
    document_id = _create_document(
        client,
        title="雪地靴评测指南",
        space_id=str(space["id"]),
        scope={
            "channel": "pinduoduo",
            "category": "雪地靴",
            "workflow": "ecommerce_customer_service_v1",
        },
    )
    version = _create_version(
        client,
        document_id,
        label="evaluation-1.0",
        content="雪地靴评测指南说明尺码范围和短毛绒内里材质。",
    )
    _publish(client, document_id, str(version["id"]))
    empty_space = _create_space(
        client,
        code="evaluation_empty",
        name="评测空知识空间",
        workflow_key="ecommerce_customer_service_v1",
    )

    for payload in (
        {
            "business_unit_id": "bu_demo",
            "knowledge_space_id": space["id"],
            "name": "尺码材质召回",
            "query": "雪地靴尺码范围和内里材质",
            "expected_titles": ["雪地靴评测指南"],
            "expect_no_grounding": False,
            "scope": {
                "channel": "pinduoduo",
                "category": "雪地靴",
                "workflow": "ecommerce_customer_service_v1",
            },
        },
        {
            "business_unit_id": "bu_demo",
            "knowledge_space_id": empty_space["id"],
            "name": "无答案问题",
            "query": "雪地靴会员积分怎么兑换",
            "expected_titles": [],
            "expect_no_grounding": True,
            "scope": {
                "channel": "pinduoduo",
                "category": "雪地靴",
                "workflow": "ecommerce_customer_service_v1",
            },
        },
    ):
        created = client.post(
            "/api/v1/knowledge/evaluation-cases",
            headers=ADMIN_HEADERS,
            json=payload,
        )
        assert created.status_code == 201, created.text

    cases = client.get(
        "/api/v1/knowledge/evaluation-cases"
        "?business_unit_id=bu_demo",
        headers=AGENT_HEADERS,
    )
    assert cases.status_code == 200
    assert len(cases.json()) == 2
    repeated = client.post(
        "/api/v1/knowledge/evaluation-cases",
        headers=ADMIN_HEADERS,
        json={
            "business_unit_id": "bu_demo",
            "knowledge_space_id": space["id"],
            "name": "尺码材质召回（重复提交复用）",
            "query": "  雪地靴尺码范围和内里材质  ",
            "expected_titles": ["雪地靴评测指南"],
            "expect_no_grounding": False,
            "scope": {
                "channel": "pinduoduo",
                "category": "雪地靴",
                "workflow": "ecommerce_customer_service_v1",
            },
        },
    )
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["id"] == next(
        item["id"]
        for item in cases.json()
        if item["knowledge_space_id"] == space["id"]
    )
    cases_after = client.get(
        "/api/v1/knowledge/evaluation-cases"
        "?business_unit_id=bu_demo",
        headers=AGENT_HEADERS,
    )
    assert cases_after.status_code == 200
    assert len(cases_after.json()) == 2

    run = client.post(
        "/api/v1/knowledge/evaluation-runs",
        headers=AGENT_HEADERS,
        json={
            "business_unit_id": "bu_demo",
            "top_k": 5,
            "min_recall_at_k": 0.8,
            "min_mrr": 0.6,
            "min_no_grounding_accuracy": 1.0,
        },
    )
    assert run.status_code == 201, run.text
    payload = run.json()
    assert payload["status"] == "SUCCEEDED"
    assert payload["verdict"] == "PASS"
    assert payload["case_count"] == 2
    assert payload["passed_cases"] == 2
    assert payload["failed_cases"] == 0
    assert payload["recall_at_k"] == 1.0
    assert payload["no_grounding_accuracy"] == 1.0
    assert len(payload["results"]) == 2

    listed = client.get(
        "/api/v1/knowledge/evaluation-runs?business_unit_id=bu_demo",
        headers=AGENT_HEADERS,
    )
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == payload["id"]

    failing_case = client.post(
        "/api/v1/knowledge/evaluation-cases",
        headers=ADMIN_HEADERS,
        json={
            "business_unit_id": "bu_demo",
            "knowledge_space_id": space["id"],
            "name": "预期文档错误",
            "query": "雪地靴尺码范围",
            "expected_titles": ["不存在的知识文档"],
            "expect_no_grounding": False,
            "scope": {
                "channel": "pinduoduo",
                "category": "雪地靴",
                "workflow": "ecommerce_customer_service_v1",
            },
        },
    )
    assert failing_case.status_code == 201
    failed_run = client.post(
        "/api/v1/knowledge/evaluation-runs",
        headers=AGENT_HEADERS,
        json={
            "business_unit_id": "bu_demo",
            "top_k": 5,
            "min_recall_at_k": 0.8,
            "min_mrr": 0.6,
            "min_no_grounding_accuracy": 0.8,
        },
    )
    assert failed_run.status_code == 201, failed_run.text
    assert failed_run.json()["verdict"] == "FAIL"
    assert failed_run.json()["failed_cases"] == 1

    repairs = client.get(
        "/api/v1/knowledge/repair-tasks?business_unit_id=bu_demo&status=OPEN",
        headers=AGENT_HEADERS,
    )
    assert repairs.status_code == 200
    assert repairs.json()["total"] == 1
    repair = repairs.json()["items"][0]
    assert repair["query"] == "雪地靴尺码范围"
    assert repair["expected_titles"] == ["不存在的知识文档"]

    closed = client.patch(
        f"/api/v1/knowledge/repair-tasks/{repair['id']}",
        headers=ADMIN_HEADERS,
        json={
            "status": "CLOSED",
            "assignee_id": "knowledge-owner",
            "resolution_note": "修正评测预期并完成回归",
        },
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "CLOSED"
    assert closed.json()["resolved_at"] is not None

    disabled_case = client.patch(
        f"/api/v1/knowledge/evaluation-cases/{failing_case.json()['id']}",
        headers=ADMIN_HEADERS,
        json={"enabled": False},
    )
    assert disabled_case.status_code == 200
    assert disabled_case.json()["enabled"] is False
    repaired_run = client.post(
        "/api/v1/knowledge/evaluation-runs",
        headers=AGENT_HEADERS,
        json={"business_unit_id": "bu_demo", "top_k": 5},
    )
    assert repaired_run.status_code == 201
    assert repaired_run.json()["verdict"] == "PASS"
    assert repaired_run.json()["case_count"] == 2


def test_evaluation_gate_blocks_failed_publish_and_rolls_back(
    client: TestClient,
) -> None:
    space = _create_space(
        client,
        code="gated_knowledge",
        name="发布门禁知识",
        workflow_key="ecommerce_customer_service_v1",
    )
    enabled = client.patch(
        f"/api/v1/knowledge-spaces/{space['id']}",
        headers=ADMIN_HEADERS,
        json={"evaluation_required": True},
    )
    assert enabled.status_code == 200
    document_id = _create_document(
        client,
        title="门禁雪地靴指南",
        space_id=str(space["id"]),
        scope={
            "channel": "pinduoduo",
            "category": "雪地靴",
            "workflow": "ecommerce_customer_service_v1",
        },
    )
    version = _create_version(
        client,
        document_id,
        label="gated-1.0",
        content="门禁雪地靴指南说明鞋面为牛剖层革。",
    )
    wrong_case = client.post(
        "/api/v1/knowledge/evaluation-cases",
        headers=ADMIN_HEADERS,
        json={
            "business_unit_id": "bu_demo",
            "knowledge_space_id": space["id"],
            "name": "门禁错误预期",
            "query": "雪地靴鞋面材质",
            "expected_titles": ["错误文档标题"],
            "scope": {
                "channel": "pinduoduo",
                "category": "雪地靴",
                "workflow": "ecommerce_customer_service_v1",
            },
        },
    )
    assert wrong_case.status_code == 201
    blocked = client.post(
        f"/api/v1/knowledge-documents/{document_id}/versions/{version['id']}/publish",
        headers=ADMIN_HEADERS,
        json={"release_note": "gate test"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "KNOWLEDGE_EVALUATION_GATE_FAILED"
    drafts = client.get(
        f"/api/v1/knowledge-documents/{document_id}/versions",
        headers=AGENT_HEADERS,
    ).json()
    assert drafts[0]["status"] == "DRAFT"
    repairs = client.get(
        "/api/v1/knowledge/repair-tasks?business_unit_id=bu_demo&status=OPEN",
        headers=AGENT_HEADERS,
    ).json()
    assert repairs["total"] == 1
    repair_id = repairs["items"][0]["id"]
    failed_verify = client.post(
        f"/api/v1/knowledge/repair-tasks/{repair_id}/verify",
        headers=AGENT_HEADERS,
    )
    assert failed_verify.status_code == 200, failed_verify.text
    assert failed_verify.json()["status"] == "IN_REPAIR"

    client.patch(
        f"/api/v1/knowledge/evaluation-cases/{wrong_case.json()['id']}",
        headers=ADMIN_HEADERS,
        json={"enabled": False},
    )
    correct_case = client.post(
        "/api/v1/knowledge/evaluation-cases",
        headers=ADMIN_HEADERS,
        json={
            "business_unit_id": "bu_demo",
            "knowledge_space_id": space["id"],
            "name": "门禁正确预期",
            "query": "雪地靴鞋面材质",
            "expected_titles": ["门禁雪地靴指南"],
            "scope": {
                "channel": "pinduoduo",
                "category": "雪地靴",
                "workflow": "ecommerce_customer_service_v1",
            },
        },
    )
    assert correct_case.status_code == 201
    published = client.post(
        f"/api/v1/knowledge-documents/{document_id}/versions/{version['id']}/publish",
        headers=ADMIN_HEADERS,
        json={"release_note": "gate passes"},
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "ACTIVE"
    verified = client.post(
        f"/api/v1/knowledge/repair-tasks/{repair_id}/verify",
        headers=AGENT_HEADERS,
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "VERIFIED"


def test_negative_feedback_creates_repair_task(client: TestClient) -> None:
    space = _create_space(
        client,
        code="feedback_presales",
        name="反馈售前知识",
        workflow_key="ecommerce_customer_service_v1",
    )
    negative = client.post(
        "/api/v1/knowledge/feedback",
        headers=AGENT_HEADERS,
        json={
            "business_unit_id": "bu_demo",
            "knowledge_space_id": space["id"],
            "query": "雪地靴是否支持免费刻字？",
            "answer": "支持。",
            "rating": "NEGATIVE",
            "reason_code": "WRONG_ANSWER",
            "details": "店铺实际不支持刻字",
        },
    )
    assert negative.status_code == 201, negative.text
    assert negative.json()["repair_task_id"] is not None

    positive = client.post(
        "/api/v1/knowledge/feedback",
        headers=AGENT_HEADERS,
        json={
            "business_unit_id": "bu_demo",
            "knowledge_space_id": space["id"],
            "query": "雪地靴内里材质",
            "answer": "短毛绒",
            "rating": "POSITIVE",
            "reason_code": "HELPFUL",
        },
    )
    assert positive.status_code == 201
    assert positive.json()["repair_task_id"] is None

    repairs = client.get(
        "/api/v1/knowledge/repair-tasks?business_unit_id=bu_demo&status=OPEN",
        headers=AGENT_HEADERS,
    )
    assert repairs.status_code == 200
    assert repairs.json()["total"] == 1
    assert repairs.json()["items"][0]["title"] == "用户负反馈：回答内容错误"
    assert repairs.json()["items"][0]["query"] == "雪地靴是否支持免费刻字？"
    assert repairs.json()["items"][0]["priority"] == "P1"

    feedback = client.get(
        "/api/v1/knowledge/feedback?business_unit_id=bu_demo",
        headers=AGENT_HEADERS,
    )
    assert feedback.status_code == 200
    assert feedback.json()["total"] == 2
    clusters = client.get(
        "/api/v1/knowledge/feedback/clusters?business_unit_id=bu_demo",
        headers=AGENT_HEADERS,
    )
    assert clusters.status_code == 200
    assert clusters.json()["total"] == 1
    assert clusters.json()["items"][0]["reason_code"] == "WRONG_ANSWER"
    assert clusters.json()["items"][0]["count"] == 1


def test_repeated_negative_feedback_reuses_active_repair_task(
    client: TestClient,
) -> None:
    queries = [
        "历史对话：\n用户：重复退款问题\n当前问题：重复退款问题",
        (
            "历史对话：\n用户：重复退款问题\n用户：重复退款问题\n"
            "用户：重复退款问题\n当前问题：重复退款问题"
        ),
    ]
    repair_ids: list[str] = []
    for query in queries:
        response = client.post(
            "/api/v1/knowledge/feedback",
            headers=AGENT_HEADERS,
            json={
                "business_unit_id": "bu_demo",
                "knowledge_space_id": None,
                "query": query,
                "answer": "错误答案",
                "rating": "NEGATIVE",
                "reason_code": "WRONG_ANSWER",
                "details": "同一问题重复反馈",
            },
        )
        assert response.status_code == 201, response.text
        repair_ids.append(response.json()["repair_task_id"])

    assert repair_ids[0] == repair_ids[1]
    repairs = client.get(
        "/api/v1/knowledge/repair-tasks?business_unit_id=bu_demo",
        headers=AGENT_HEADERS,
    )
    assert repairs.status_code == 200
    assert repairs.json()["total"] == 1
    assert repairs.json()["items"][0]["query"] == "重复退款问题"
    assert repairs.json()["items"][0]["occurrence_count"] == 2


def test_rag_metrics_summarize_grounded_drafts(client: TestClient) -> None:
    document_id = _create_document(client)
    version = _create_version(
        client,
        document_id,
        label="metrics-1.0",
        content="团队消息通知在设置中心完成配置。",
    )
    _publish(client, document_id, str(version["id"]))
    client.post(
        "/api/v1/tickets",
        headers={
            **AGENT_HEADERS,
            "Idempotency-Key": "metrics-ticket:001",
        },
        json={
            "business_unit_id": "bu_demo",
            "source": {
                "system": "demo_helpdesk",
                "channel": "web_form",
                "external_ticket_id": "METRICS-TICKET-001",
            },
            "requester": {
                "external_ref": "customer-metrics",
                "customer_tier": "standard",
            },
            "subject": "如何配置团队消息通知",
            "body": "请说明通知配置方法。",
            "locale": "zh-CN",
            "attachments": [],
            "metadata": {},
        },
    )

    response = client.get(
        "/api/v1/metrics/rag?business_unit_id=bu_demo",
        headers={"X-Actor-Id": "auditor-1", "X-Actor-Role": "auditor"},
    )

    assert response.status_code == 200
    assert response.json()["draft_count"] == 1
    assert response.json()["grounded_count"] == 1
    assert response.json()["grounding_rate"] == 1.0
    assert response.json()["provider_counts"] == {"local": 1}
    assert response.json()["claim_count"] > 0
    assert response.json()["cited_claim_count"] > 0
    assert response.json()["semantic_verified_claim_count"] == 1
    assert response.json()["semantic_unsupported_claim_count"] == 0



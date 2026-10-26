from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import func, select

from ticket_agent.customer_service.models import (
    CustomerConversation,
    CustomerMessage,
)
from ticket_agent.ecommerce.models import (
    EcommerceListingBatchJob,
    EcommerceListingTask,
    EcommerceProductAsset,
)
from ticket_agent.knowledge.models import KnowledgeDocument, KnowledgeVersion
from ticket_agent.shared.db import SessionLocal
from ticket_agent.tickets.models import OutboxEvent, Ticket

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
ALPHA_AUDITOR = {
    "X-Actor-Id": "alpha-auditor",
    "X-Actor-Role": "auditor",
    "X-Business-Unit-Id": "bu_alpha",
}
BETA_ADMIN = {
    "X-Actor-Id": "beta-admin",
    "X-Actor-Role": "admin",
    "X-Business-Unit-Id": "bu_beta",
}
BETA_AGENT = {
    "X-Actor-Id": "beta-agent",
    "X-Actor-Role": "agent",
    "X-Business-Unit-Id": "bu_beta",
}
BETA_AUDITOR = {
    "X-Actor-Id": "beta-auditor",
    "X-Actor-Role": "auditor",
    "X-Business-Unit-Id": "bu_beta",
}
TINY_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff"
    b"\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _assert_denied(response: Response) -> None:
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "BUSINESS_UNIT_ACCESS_DENIED"


def _alpha_ticket_payload() -> dict[str, object]:
    return {
        "business_unit_id": "bu_alpha",
        "source": {
            "system": "demo_helpdesk",
            "channel": "web_form",
            "external_ticket_id": "ALPHA-TENANT-001",
        },
        "requester": {
            "external_ref": "alpha-customer",
            "customer_tier": "standard",
        },
        "subject": "Alpha 租户私有工单",
        "body": "请问管理员如何为团队配置消息通知？",
        "locale": "zh-CN",
        "attachments": [],
        "metadata": {"product": "admin_portal"},
    }


def test_tickets_reject_cross_tenant_reads_and_writes(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/v1/tickets",
        headers={**ALPHA_AGENT, "Idempotency-Key": "tenant-alpha-ticket"},
        json=_alpha_ticket_payload(),
    )
    assert created.status_code == 202, created.text
    ticket_id = created.json()["id"]

    detail = client.get(f"/api/v1/tickets/{ticket_id}", headers=ALPHA_AGENT)
    assert detail.status_code == 200, detail.text
    version = detail.json()["version"]
    status = detail.json()["status"]

    _assert_denied(client.get(f"/api/v1/tickets/{ticket_id}", headers=BETA_AGENT))
    _assert_denied(
        client.post(
            f"/api/v1/tickets/{ticket_id}/takeover",
            headers=BETA_AGENT,
            json={
                "expected_version": version,
                "reason_code": "AGENT_REQUESTED",
            },
        )
    )
    _assert_denied(
        client.post(
            f"/api/v1/tickets/{ticket_id}/reviews",
            headers=BETA_AGENT,
            json={
                "expected_version": version,
                "decision": "ACCEPTED",
                "reason_code": "AGENT_APPROVED",
            },
        )
    )
    _assert_denied(
        client.post(
            f"/api/v1/tickets/{ticket_id}/sync-attempts",
            headers=BETA_AGENT,
            json={"expected_version": version},
        )
    )
    _assert_denied(
        client.post(
            f"/api/v1/tickets/{ticket_id}/classification-overrides",
            headers=BETA_AGENT,
            json={
                "expected_version": version,
                "primary": "OTHER",
                "secondary": "OTHER",
                "reason_code": "CROSS_TENANT",
            },
        )
    )
    _assert_denied(
        client.post(
            f"/api/v1/tickets/{ticket_id}/archive-test-data",
            headers=BETA_ADMIN,
        )
    )
    _assert_denied(
        client.post(
            "/api/v1/tickets/test-cleanup",
            headers=BETA_ADMIN,
            params={
                "business_unit_id": "bu_alpha",
                "requester_prefix": "alpha-customer",
            },
        )
    )
    _assert_denied(
        client.get(
            "/api/v1/tickets?business_unit_id=bu_alpha",
            headers=BETA_AGENT,
        )
    )
    beta_list = client.get("/api/v1/tickets", headers=BETA_AGENT)
    assert beta_list.status_code == 200, beta_list.text
    assert ticket_id not in {item["id"] for item in beta_list.json()["items"]}

    with SessionLocal() as session:
        before_events = session.scalar(select(func.count()).select_from(OutboxEvent))
    _assert_denied(
        client.post(
            "/api/v1/tickets/sync-attempts:batch",
            headers=BETA_ADMIN,
            json={"ticket_ids": [ticket_id]},
        )
    )
    with SessionLocal() as session:
        after_events = session.scalar(select(func.count()).select_from(OutboxEvent))
        stored = session.get(Ticket, UUID(ticket_id))
        assert stored is not None
        assert stored.version == version
        assert stored.status == status
    assert after_events == before_events

    _assert_denied(
        client.post(
            "/api/v1/tickets",
            headers={**BETA_AGENT, "Idempotency-Key": "tenant-alpha-ticket"},
            json={
                **_alpha_ticket_payload(),
                "business_unit_id": "bu_beta",
            },
        )
    )
    _assert_denied(
        client.post(
            "/api/v1/tickets",
            headers={**BETA_AGENT, "Idempotency-Key": "tenant-beta-ticket"},
            json=_alpha_ticket_payload(),
        )
    )

    alpha_detail = client.get(f"/api/v1/tickets/{ticket_id}", headers=ALPHA_AGENT)
    assert alpha_detail.status_code == 200, alpha_detail.text
    assert alpha_detail.json()["version"] == version


def test_knowledge_rejects_cross_tenant_reads_and_writes(
    client: TestClient,
) -> None:
    document = client.post(
        "/api/v1/knowledge-documents",
        headers=ALPHA_ADMIN,
        json={
            "business_unit_id": "bu_alpha",
            "title": "Alpha 私有知识",
            "doc_type": "SOP",
            "owner_id": "alpha-admin",
        },
    )
    assert document.status_code == 201, document.text
    document_id = document.json()["id"]

    version = client.post(
        f"/api/v1/knowledge-documents/{document_id}/versions",
        headers=ALPHA_ADMIN,
        json={
            "version_label": "1.0",
            "content": "Alpha 私有知识：仅允许本租户成员读取和使用。",
            "effective_from": datetime.now(UTC).isoformat(),
        },
    )
    assert version.status_code == 201, version.text
    version_id = version.json()["id"]

    _assert_denied(
        client.patch(
            f"/api/v1/knowledge-documents/{document_id}",
            headers=BETA_ADMIN,
            json={"title": "越权修改"},
        )
    )
    _assert_denied(
        client.post(
            f"/api/v1/knowledge-documents/{document_id}/archive",
            headers=BETA_ADMIN,
        )
    )
    _assert_denied(
        client.post(
            f"/api/v1/knowledge-documents/{document_id}/restore",
            headers=BETA_ADMIN,
        )
    )
    _assert_denied(
        client.post(
            f"/api/v1/knowledge-documents/{document_id}/versions",
            headers=BETA_ADMIN,
            json={
                "version_label": "1.1",
                "content": "跨租户新增版本内容不应被创建。",
                "effective_from": datetime.now(UTC).isoformat(),
            },
        )
    )
    _assert_denied(
        client.post(
            f"/api/v1/knowledge-documents/{document_id}/uploads",
            headers={**BETA_ADMIN, "Content-Type": "text/plain"},
            params={"version_label": "1.2", "filename": "alpha.txt"},
            content=b"cross tenant upload",
        )
    )
    _assert_denied(
        client.post(
            f"/api/v1/knowledge-documents/{document_id}/versions/from-file",
            headers={**BETA_ADMIN, "Content-Type": "text/plain"},
            params={"version_label": "1.3", "filename": "alpha.txt"},
            content=b"cross tenant upload",
        )
    )
    _assert_denied(
        client.get(
            f"/api/v1/knowledge-documents/{document_id}/versions/{version_id}",
            headers=BETA_ADMIN,
        )
    )
    _assert_denied(
        client.get(
            f"/api/v1/knowledge-documents/{document_id}/versions",
            headers=BETA_ADMIN,
        )
    )
    _assert_denied(
        client.post(
            f"/api/v1/knowledge-documents/{document_id}/versions/{version_id}/publish",
            headers=BETA_ADMIN,
            json={"release_note": "cross tenant"},
        )
    )

    beta_documents = client.get("/api/v1/knowledge-documents", headers=BETA_AGENT)
    assert beta_documents.status_code == 200, beta_documents.text
    assert beta_documents.json() == []
    alpha_documents = client.get("/api/v1/knowledge-documents", headers=ALPHA_AGENT)
    assert alpha_documents.status_code == 200, alpha_documents.text
    assert document_id in {item["id"] for item in alpha_documents.json()}

    case = client.post(
        "/api/v1/knowledge/evaluation-cases",
        headers=ALPHA_ADMIN,
        json={
            "business_unit_id": "bu_alpha",
            "name": "Alpha 评测",
            "query": "Alpha 私有知识",
            "expected_titles": ["Alpha 私有知识"],
        },
    )
    assert case.status_code == 201, case.text
    _assert_denied(
        client.patch(
            f"/api/v1/knowledge/evaluation-cases/{case.json()['id']}",
            headers=BETA_ADMIN,
            json={"name": "越权修改"},
        )
    )

    with SessionLocal() as session:
        stored_document = session.get(KnowledgeDocument, UUID(document_id))
        assert stored_document is not None
        assert stored_document.status == "DRAFT"
        versions = session.scalars(
            select(KnowledgeVersion).where(KnowledgeVersion.document_id == UUID(document_id))
        ).all()
        assert len(versions) == 1
        assert versions[0].status == "DRAFT"


def test_customer_service_rejects_cross_tenant_conversation_access(
    client: TestClient,
) -> None:
    conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=ALPHA_AGENT,
        json={
            "business_unit_id": "bu_alpha",
            "requester_ref": "alpha-buyer",
            "channel": "enterprise_service",
        },
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]

    _assert_denied(
        client.get(
            f"/api/v1/customer-service/conversations/{conversation_id}",
            headers=BETA_AGENT,
        )
    )
    _assert_denied(
        client.get(
            f"/api/v1/customer-service/conversations/{conversation_id}/events",
            headers=BETA_AGENT,
        )
    )
    _assert_denied(
        client.post(
            f"/api/v1/customer-service/conversations/{conversation_id}/messages",
            headers=BETA_AGENT,
            json={"content": "跨租户消息"},
        )
    )
    _assert_denied(
        client.post(
            f"/api/v1/customer-service/conversations/{conversation_id}/takeover",
            headers=BETA_AGENT,
            json={"expected_version": 1},
        )
    )
    _assert_denied(
        client.post(
            f"/api/v1/customer-service/conversations/{conversation_id}/release",
            headers=BETA_AGENT,
        )
    )
    _assert_denied(
        client.post(
            f"/api/v1/customer-service/conversations/{conversation_id}/manual-replies",
            headers=BETA_AGENT,
            json={"content": "跨租户人工回复"},
        )
    )
    _assert_denied(
        client.post(
            f"/api/v1/customer-service/conversations/{conversation_id}/reply-suggestions",
            headers=BETA_AGENT,
        )
    )
    _assert_denied(
        client.post(
            f"/api/v1/customer-service/conversations/{conversation_id}/reply-optimizations",
            headers=BETA_AGENT,
            json={"text": "跨租户优化", "style": "concise"},
        )
    )
    _assert_denied(
        client.post(
            f"/api/v1/customer-service/conversations/{conversation_id}/reassign",
            headers=BETA_ADMIN,
            json={
                "expected_version": 1,
                "agent_id": "beta-agent",
            },
        )
    )

    beta_list = client.get("/api/v1/customer-service/conversations", headers=BETA_AGENT)
    assert beta_list.status_code == 200, beta_list.text
    assert conversation_id not in {item["id"] for item in beta_list.json()["items"]}

    _assert_denied(
        client.post(
            "/api/v1/customer-service/conversations",
            headers=BETA_AGENT,
            json={
                "business_unit_id": "bu_alpha",
                "requester_ref": "cross-tenant-buyer",
                "channel": "enterprise_service",
            },
        )
    )

    alpha_view = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}",
        headers=ALPHA_AGENT,
    )
    assert alpha_view.status_code == 200, alpha_view.text
    with SessionLocal() as session:
        stored = session.get(CustomerConversation, UUID(conversation_id))
        assert stored is not None
        assert stored.version == 1
        assert stored.assigned_agent_id is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(CustomerMessage)
                .where(CustomerMessage.conversation_id == UUID(conversation_id))
            )
            == 0
        )


def test_ecommerce_rejects_cross_tenant_resource_access(
    client: TestClient,
) -> None:
    product = client.post(
        "/api/v1/ecommerce/products",
        headers=ALPHA_ADMIN,
        json={
            "business_unit_id": "bu_alpha",
            "sku": "ALPHA-CUP-001",
            "name": "Alpha 私有商品",
            "category": "家居日用",
            "brand": "Alpha 品牌",
            "price": 39.9,
            "attributes": {"材质": "食品级硅胶"},
        },
    )
    assert product.status_code == 201, product.text
    product_id = product.json()["id"]

    asset = client.post(
        f"/api/v1/ecommerce/products/{product_id}/assets",
        headers={**ALPHA_AGENT, "Content-Type": "image/png"},
        params={"filename": "cover.png"},
        content=TINY_PNG,
    )
    assert asset.status_code == 201, asset.text
    asset_id = asset.json()["id"]

    listing = client.post(
        "/api/v1/ecommerce/listing-tasks",
        headers=ALPHA_AGENT,
        params={"business_unit_id": "bu_alpha"},
        json={"product_id": product_id, "channel": "pinduoduo_sandbox"},
    )
    assert listing.status_code == 201, listing.text
    task_id = listing.json()["id"]
    task_status = listing.json()["status"]

    category = client.post(
        "/api/v1/ecommerce/categories",
        headers=ALPHA_ADMIN,
        json={
            "business_unit_id": "bu_alpha",
            "channel": "pinduoduo_sandbox",
            "code": "alpha_private_category",
            "name": "Alpha 私有品类",
            "required_attributes": ["容量"],
        },
    )
    assert category.status_code == 201, category.text
    category_id = category.json()["id"]

    beta_products = client.get("/api/v1/ecommerce/products", headers=BETA_AGENT)
    assert beta_products.status_code == 200, beta_products.text
    assert beta_products.json() == []
    beta_tasks = client.get("/api/v1/ecommerce/listing-tasks", headers=BETA_AGENT)
    assert beta_tasks.status_code == 200, beta_tasks.text
    assert beta_tasks.json()["total"] == 0

    _assert_denied(
        client.get(
            f"/api/v1/ecommerce/listing-tasks/{task_id}",
            headers=BETA_AGENT,
        )
    )
    _assert_denied(
        client.get(
            f"/api/v1/ecommerce/listing-tasks/{task_id}/export",
            headers=BETA_AGENT,
        )
    )
    _assert_denied(
        client.get(
            f"/api/v1/ecommerce/assets/{asset_id}/content",
            headers=BETA_AGENT,
        )
    )
    _assert_denied(
        client.post(
            f"/api/v1/ecommerce/products/{product_id}/assets",
            headers={**BETA_AGENT, "Content-Type": "image/png"},
            params={"filename": "intruder.png"},
            content=TINY_PNG,
        )
    )
    _assert_denied(
        client.get(
            f"/api/v1/ecommerce/categories/{category_id}/import-template",
            headers=BETA_AGENT,
        )
    )
    _assert_denied(
        client.post(
            "/api/v1/ecommerce/products/import/preview",
            headers={**BETA_AGENT, "Content-Type": "text/csv; charset=utf-8"},
            params={"category_profile_id": category_id},
            content=b"sku,name\nALPHA-X,alpha\n",
        )
    )

    with SessionLocal() as session:
        before_jobs = session.scalar(select(func.count()).select_from(EcommerceListingBatchJob))
    _assert_denied(
        client.post(
            "/api/v1/ecommerce/listing-batch-jobs",
            headers=BETA_AGENT,
            json={"product_ids": [product_id], "channel": "pinduoduo_sandbox"},
        )
    )
    with SessionLocal() as session:
        after_jobs = session.scalar(select(func.count()).select_from(EcommerceListingBatchJob))
        stored_task = session.get(EcommerceListingTask, UUID(task_id))
        assert stored_task is not None
        assert stored_task.status == task_status
        assets = session.scalars(
            select(EcommerceProductAsset).where(
                EcommerceProductAsset.product_id == UUID(product_id)
            )
        ).all()
        assert len(assets) == 1
    assert after_jobs == before_jobs

    alpha_task = client.get(f"/api/v1/ecommerce/listing-tasks/{task_id}", headers=ALPHA_AGENT)
    assert alpha_task.status_code == 200, alpha_task.text


def test_observability_is_scoped_to_the_actor_business_unit(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/v1/tickets",
        headers={**ALPHA_AGENT, "Idempotency-Key": "tenant-alpha-observability"},
        json=_alpha_ticket_payload(),
    )
    assert created.status_code == 202, created.text

    alpha_runs = client.get("/api/v1/agent-runs", headers=ALPHA_AUDITOR)
    assert alpha_runs.status_code == 200, alpha_runs.text
    assert alpha_runs.json()["total"] >= 1
    run = alpha_runs.json()["items"][0]

    beta_runs = client.get("/api/v1/agent-runs", headers=BETA_AUDITOR)
    assert beta_runs.status_code == 200, beta_runs.text
    assert beta_runs.json()["total"] == 0

    _assert_denied(
        client.get(
            f"/api/v1/agent-runs/{run['id']}/trace",
            headers=BETA_AUDITOR,
        )
    )
    _assert_denied(
        client.get(
            f"/api/v1/agent-runs?employee_id={run['employee_id']}",
            headers=BETA_AUDITOR,
        )
    )
    _assert_denied(
        client.get(
            f"/api/v1/tool-calls?employee_id={run['employee_id']}",
            headers=BETA_AUDITOR,
        )
    )
    _assert_denied(
        client.get(
            f"/api/v1/metrics/models/budget?employee_id={run['employee_id']}",
            headers=BETA_AUDITOR,
        )
    )

    beta_calls = client.get("/api/v1/tool-calls", headers=BETA_AUDITOR)
    assert beta_calls.status_code == 200, beta_calls.text
    assert beta_calls.json()["total"] == 0
    beta_tool_metrics = client.get("/api/v1/metrics/tools", headers=BETA_AUDITOR)
    assert beta_tool_metrics.status_code == 200, beta_tool_metrics.text
    assert beta_tool_metrics.json()["calls"] == 0
    beta_model_metrics = client.get("/api/v1/metrics/models", headers=BETA_AUDITOR)
    assert beta_model_metrics.status_code == 200, beta_model_metrics.text
    assert beta_model_metrics.json()["calls"] == 0
    beta_sync_metrics = client.get("/api/v1/metrics/sync", headers=BETA_AUDITOR)
    assert beta_sync_metrics.status_code == 200, beta_sync_metrics.text
    assert beta_sync_metrics.json()["attempted"] == 0
    beta_rag_metrics = client.get("/api/v1/metrics/rag", headers=BETA_AUDITOR)
    assert beta_rag_metrics.status_code == 200, beta_rag_metrics.text
    assert beta_rag_metrics.json()["draft_count"] == 0

    alpha_trace = client.get(
        f"/api/v1/agent-runs/{run['id']}/trace",
        headers=ALPHA_AUDITOR,
    )
    assert alpha_trace.status_code == 200, alpha_trace.text
    alpha_calls = client.get(
        f"/api/v1/tool-calls?employee_id={run['employee_id']}",
        headers=ALPHA_AUDITOR,
    )
    assert alpha_calls.status_code == 200, alpha_calls.text
    assert alpha_calls.json()["total"] >= 1


OMITTED_BU_ADMIN = {
    "X-Actor-Id": "omitted-bu-admin",
    "X-Actor-Role": "admin",
    "X-Business-Unit-Id": "bu_omitted_defaults",
}
DEMO_ADMIN = {
    "X-Actor-Id": "demo-admin",
    "X-Actor-Role": "admin",
    "X-Business-Unit-Id": "bu_demo",
}
DEFAULTED_LIST_ENDPOINTS = [
    "/api/v1/skills",
    "/api/v1/business-service-entries",
    "/api/v1/workforce/tasks",
    "/api/v1/mcp/connectors",
    "/api/v1/mcp/tool-approvals",
    "/api/v1/mcp/action-incidents",
    "/api/v1/digital-employee-templates",
    "/api/v1/digital-employee-route-rules",
    "/api/v1/digital-employee-route-decisions",
    "/api/v1/digital-employee-templates/managed",
    "/api/v1/digital-employee-drafts",
]


def test_list_endpoints_default_to_the_actor_business_unit(
    client: TestClient,
) -> None:
    def _skill_payload(business_unit_id: str, code: str) -> dict[str, object]:
        return {
            "business_unit_id": business_unit_id,
            "code": code,
            "name": code,
            "description": "",
            "instructions": "回答时先确认租户上下文。",
            "triggers": [],
            "tools": [],
            "status": "ACTIVE",
        }

    own_skill = client.post(
        "/api/v1/skills",
        headers=OMITTED_BU_ADMIN,
        json=_skill_payload("bu_omitted_defaults", "tenant-defaults-own"),
    )
    assert own_skill.status_code == 201, own_skill.text
    demo_skill = client.post(
        "/api/v1/skills",
        headers=DEMO_ADMIN,
        json=_skill_payload("bu_demo", "tenant-defaults-demo"),
    )
    assert demo_skill.status_code == 201, demo_skill.text

    omitted_list = client.get("/api/v1/skills", headers=OMITTED_BU_ADMIN)
    assert omitted_list.status_code == 200, omitted_list.text
    listed_ids = {item["id"] for item in omitted_list.json()}
    assert own_skill.json()["id"] in listed_ids
    assert demo_skill.json()["id"] not in listed_ids
    assert {item["business_unit_id"] for item in omitted_list.json()} == {"bu_omitted_defaults"}

    for path in DEFAULTED_LIST_ENDPOINTS:
        defaulted = client.get(path, headers=OMITTED_BU_ADMIN)
        assert defaulted.status_code == 200, (path, defaulted.text)
        foreign = client.get(
            f"{path}?business_unit_id=bu_demo",
            headers=OMITTED_BU_ADMIN,
        )
        _assert_denied(foreign)

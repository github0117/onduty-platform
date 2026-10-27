from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import update

from ticket_agent.knowledge.models import KnowledgeVersion
from ticket_agent.shared.db import SessionLocal

ADMIN_HEADERS = {
    "X-Actor-Id": "admin-1",
    "X-Actor-Role": "admin",
}
AGENT_HEADERS = {
    "X-Actor-Id": "agent-1",
    "X-Actor-Role": "agent",
}
MULTI_UNIT_ADMIN_HEADERS = {
    **ADMIN_HEADERS,
    "X-Business-Units": "bu_demo,bu_other",
}


def _create_published_version(client: TestClient) -> tuple[str, str]:
    document = client.post(
        "/api/v1/knowledge-documents",
        headers=ADMIN_HEADERS,
        json={
            "business_unit_id": "bu_demo",
            "title": "退款政策",
            "doc_type": "SOP",
            "owner_id": "admin-1",
            "scope": {},
        },
    )
    assert document.status_code == 201, document.text
    document_id = str(document.json()["id"])
    version = client.post(
        f"/api/v1/knowledge-documents/{document_id}/versions",
        headers=ADMIN_HEADERS,
        json={
            "version_label": "1.0",
            "content": "签收后七天内可以申请退款。跨境订单不支持无理由退款。",
            "effective_from": datetime.now(UTC).isoformat(),
        },
    )
    assert version.status_code == 201, version.text
    version_id = str(version.json()["id"])
    published = client.post(
        f"/api/v1/knowledge-documents/{document_id}/versions/{version_id}/publish",
        headers=ADMIN_HEADERS,
        json={"release_note": "reindex test"},
    )
    assert published.status_code == 200, published.text
    return document_id, version_id


def _mark_versions_stale(embedding_model: str) -> None:
    with SessionLocal() as session:
        session.execute(
            update(KnowledgeVersion).values(embedding_model=embedding_model)
        )
        session.commit()


def _search(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/v1/knowledge/search",
        headers=AGENT_HEADERS,
        json={
            "query": "签收后多久可以退款",
            "business_unit_id": "bu_demo",
            "top_k": 3,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_reindex_restores_search_after_model_change(client: TestClient) -> None:
    _, version_id = _create_published_version(client)
    assert _search(client)["items"]

    _mark_versions_stale("legacy-embedding-model")
    assert _search(client)["items"] == []

    metrics_before = client.get(
        "/api/v1/metrics/rag",
        headers=ADMIN_HEADERS,
        params={"business_unit_id": "bu_demo"},
    )
    assert metrics_before.status_code == 200, metrics_before.text
    assert metrics_before.json()["reindex_pending_versions"] >= 1

    response = client.post(
        "/api/v1/knowledge/reindex",
        headers=ADMIN_HEADERS,
        json={"business_unit_id": "bu_demo"},
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]

    job = client.get(f"/api/v1/knowledge/reindex-jobs/{job_id}", headers=ADMIN_HEADERS)
    assert job.status_code == 200, job.text
    assert job.json()["status"] == "SUCCEEDED"
    assert job.json()["processed_versions"] >= 1
    assert job.json()["failed_versions"] == 0

    with SessionLocal() as session:
        refreshed = session.get(KnowledgeVersion, UUID(version_id))
        assert refreshed is not None
        assert refreshed.embedding_model.startswith("local-hash-")

    assert _search(client)["items"]
    metrics_after = client.get(
        "/api/v1/metrics/rag",
        headers=ADMIN_HEADERS,
        params={"business_unit_id": "bu_demo"},
    )
    assert metrics_after.json()["reindex_pending_versions"] == 0


def test_repeat_reindex_is_idempotent(client: TestClient) -> None:
    _create_published_version(client)
    first = client.post(
        "/api/v1/knowledge/reindex",
        headers=ADMIN_HEADERS,
        json={"business_unit_id": "bu_demo"},
    )
    assert first.status_code == 202, first.text
    second = client.post(
        "/api/v1/knowledge/reindex",
        headers=ADMIN_HEADERS,
        json={"business_unit_id": "bu_demo"},
    )
    assert second.status_code == 202, second.text
    job = client.get(
        f"/api/v1/knowledge/reindex-jobs/{second.json()['id']}",
        headers=ADMIN_HEADERS,
    ).json()

    assert job["status"] == "SUCCEEDED"
    assert job["processed_versions"] == 0
    assert job["skipped_versions"] >= 1


def test_reindex_is_denied_for_non_admin(client: TestClient) -> None:
    response = client.post(
        "/api/v1/knowledge/reindex",
        headers=AGENT_HEADERS,
        json={"business_unit_id": "bu_demo"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"

    listing = client.get("/api/v1/knowledge/reindex-jobs", headers=AGENT_HEADERS)
    assert listing.status_code == 403


def test_reindex_rejects_document_from_another_business_unit(
    client: TestClient,
) -> None:
    document_id, _ = _create_published_version(client)
    response = client.post(
        "/api/v1/knowledge/reindex",
        headers=MULTI_UNIT_ADMIN_HEADERS,
        json={"business_unit_id": "bu_other", "document_id": document_id},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "SCHEMA_VALIDATION_FAILED"


def test_reindex_jobs_list_is_scoped_to_business_unit(client: TestClient) -> None:
    _create_published_version(client)
    created = client.post(
        "/api/v1/knowledge/reindex",
        headers=ADMIN_HEADERS,
        json={"business_unit_id": "bu_demo"},
    )
    assert created.status_code == 202, created.text

    listing = client.get(
        "/api/v1/knowledge/reindex-jobs",
        headers=ADMIN_HEADERS,
        params={"business_unit_id": "bu_demo"},
    )
    assert listing.status_code == 200, listing.text
    job_ids = {item["id"] for item in listing.json()["items"]}
    assert created.json()["id"] in job_ids

    other = client.get(
        "/api/v1/knowledge/reindex-jobs",
        headers=MULTI_UNIT_ADMIN_HEADERS,
        params={"business_unit_id": "bu_other"},
    )
    assert other.status_code == 200
    assert other.json()["items"] == []

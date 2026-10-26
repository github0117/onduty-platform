#!/usr/bin/env python3
import json
import sys
import time
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import httpx


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    suffix = uuid4().hex[:8]
    admin = {
        "X-Actor-Id": "acceptance-admin",
        "X-Actor-Role": "admin",
        "X-Business-Unit-Id": "bu_acceptance",
    }
    agent = {
        "X-Actor-Id": "acceptance-agent",
        "X-Actor-Role": "agent",
        "X-Business-Unit-Id": "bu_acceptance",
    }
    auditor = {
        "X-Actor-Id": "acceptance-auditor",
        "X-Actor-Role": "auditor",
        "X-Business-Unit-Id": "bu_acceptance",
    }

    with httpx.Client(base_url=base_url, timeout=30) as client:
        health = client.get("/health/ready")
        health.raise_for_status()

        document_response = client.post(
            "/api/v1/knowledge-documents",
            headers=admin,
            json={
                "business_unit_id": "bu_acceptance",
                "title": f"真实基础设施验收指引 {suffix}",
                "doc_type": "SOP",
                "owner_id": "acceptance-admin",
                "scope": {"products": ["acceptance_portal"]},
            },
        )
        document_response.raise_for_status()
        document_id = document_response.json()["id"]

        upload_response = client.post(
            f"/api/v1/knowledge-documents/{document_id}/uploads",
            headers={**admin, "Content-Type": "text/markdown"},
            params={
                "version_label": "1.0",
                "filename": f"acceptance-{suffix}.md",
            },
            content=(
                "# 验收指引\n\n"
                "管理员进入验收门户，打开通知设置，选择团队范围并保存配置。\n"
            ).encode(),
        )
        upload_response.raise_for_status()
        version_id = upload_response.json()["version_id"]

        ingested = _wait(
            client,
            f"/api/v1/knowledge-documents/{document_id}/versions/{version_id}",
            headers=agent,
            predicate=lambda payload: payload["status"] in {"DRAFT", "FAILED"},
        )
        if ingested["status"] != "DRAFT":
            raise RuntimeError(f"Knowledge ingestion failed: {ingested['ingestion_error']}")

        publish_response = client.post(
            (
                f"/api/v1/knowledge-documents/{document_id}/versions/"
                f"{version_id}/publish"
            ),
            headers=admin,
            json={"release_note": "real infrastructure acceptance"},
        )
        publish_response.raise_for_status()

        ticket_response = client.post(
            "/api/v1/tickets",
            headers={**agent, "Idempotency-Key": f"acceptance:{suffix}"},
            json={
                "business_unit_id": "bu_acceptance",
                "source": {
                    "system": "acceptance_helpdesk",
                    "channel": "web_form",
                    "external_ticket_id": f"ACCEPTANCE-{suffix}",
                },
                "requester": {
                    "external_ref": f"customer-{suffix}",
                    "customer_tier": "standard",
                },
                "subject": "如何配置验收门户通知",
                "body": "请指导管理员打开通知设置并保存团队范围。",
                "locale": "zh-CN",
                "attachments": [],
                "metadata": {"product": "acceptance_portal"},
            },
        )
        ticket_response.raise_for_status()
        ticket_id = ticket_response.json()["id"]

        before = _wait(
            client,
            f"/api/v1/tickets/{ticket_id}",
            headers=agent,
            predicate=lambda payload: payload["workflow_state"]
            in {"PENDING_REVIEW", "NEEDS_HUMAN"},
        )
        if before["workflow_state"] != "PENDING_REVIEW":
            raise RuntimeError(
                f"Ticket did not reach review: {before['workflow_state']}"
            )

        review_response = client.post(
            f"/api/v1/tickets/{ticket_id}/reviews",
            headers=agent,
            json={
                "expected_version": before["version"],
                "decision": "ACCEPTED",
                "reason_code": "REAL_INFRA_ACCEPTED",
            },
        )
        review_response.raise_for_status()
        final = _wait(
            client,
            f"/api/v1/tickets/{ticket_id}",
            headers=agent,
            predicate=lambda payload: payload["workflow_state"]
            in {"COMPLETED", "NEEDS_HUMAN"},
        )
        if final["workflow_state"] != "COMPLETED":
            raise RuntimeError(
                f"Ticket synchronization failed: {final['workflow_state']}"
            )

        model_metrics = client.get(
            "/api/v1/metrics/models?business_unit_id=bu_acceptance",
            headers=auditor,
        )
        model_metrics.raise_for_status()
        budget = client.get(
            (
                "/api/v1/metrics/models/budget"
                f"?employee_id={before['employee']['id']}"
            ),
            headers=auditor,
        )
        budget.raise_for_status()

        client.post(
            f"/api/v1/knowledge-documents/{document_id}/archive",
            headers=admin,
        ).raise_for_status()

        print(
            json.dumps(
                {
                    "health": health.json()["status"],
                    "knowledge": {
                        "version_status": ingested["status"],
                        "chunks": publish_response.json()["chunk_count"],
                        "object_storage": "MINIO_S3",
                    },
                    "ticket": {
                        "id": ticket_id,
                        "workflow_before_review": before["workflow_state"],
                        "workflow_final": final["workflow_state"],
                        "sync": final["sync"]["status"],
                        "citations": len(before["draft"]["citations"]),
                    },
                    "model_metrics": {
                        "calls": model_metrics.json()["calls"],
                        "tokens": model_metrics.json()["total_tokens"],
                    },
                    "budget_periods": [
                        item["period"] for item in budget.json()["periods"]
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )


def _wait(
    client: httpx.Client,
    path: str,
    *,
    headers: dict[str, str],
    predicate: Callable[[dict[str, Any]], bool],
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(path, headers=headers)
        response.raise_for_status()
        last_payload = response.json()
        if predicate(last_payload):
            return last_payload
        time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for {path}: {last_payload}")


if __name__ == "__main__":
    main()

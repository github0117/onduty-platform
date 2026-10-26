#!/usr/bin/env python3
import json
import os
import tempfile
from pathlib import Path


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="ticket-smoke-") as directory:
        root = Path(directory)
        os.environ.update(
            {
                "APP_ENV": "test",
                "APP_AUTH_MODE": "dev",
                "TASK_MODE": "inline",
                "DATABASE_URL": f"sqlite:///{root / 'smoke.db'}",
                "OBJECT_STORAGE_PROVIDER": "local",
                "OBJECT_STORAGE_LOCAL_ROOT": str(root / "objects"),
                "TICKET_INTEGRATION_PROVIDER": "local",
            }
        )

        from fastapi.testclient import TestClient

        from ticket_agent.main import app

        admin = {"X-Actor-Id": "admin-1", "X-Actor-Role": "admin"}
        agent = {"X-Actor-Id": "agent-1", "X-Actor-Role": "agent"}
        auditor = {"X-Actor-Id": "auditor-1", "X-Actor-Role": "auditor"}
        with TestClient(app) as client:
            document = client.post(
                "/api/v1/knowledge-documents",
                headers=admin,
                json={
                    "business_unit_id": "bu_demo",
                    "title": "企业通知配置指南",
                    "doc_type": "SOP",
                    "owner_id": "admin-1",
                    "scope": {"products": ["admin_portal"]},
                },
            )
            document.raise_for_status()
            document_id = document.json()["id"]

            version = client.post(
                f"/api/v1/knowledge-documents/{document_id}/versions",
                headers=admin,
                json={
                    "version_label": "1.0",
                    "content": (
                        "管理员进入后台设置，打开消息通知，"
                        "选择团队范围并保存配置。"
                    ),
                },
            )
            version.raise_for_status()
            version_id = version.json()["id"]
            published = client.post(
                (
                    f"/api/v1/knowledge-documents/{document_id}/versions/"
                    f"{version_id}/publish"
                ),
                headers=admin,
                json={"release_note": "smoke"},
            )
            published.raise_for_status()

            created = client.post(
                "/api/v1/tickets",
                headers={**agent, "Idempotency-Key": "smoke:close-loop-001"},
                json={
                    "business_unit_id": "bu_demo",
                    "source": {
                        "system": "demo_helpdesk",
                        "channel": "web_form",
                        "external_ticket_id": "CLOSE-LOOP-001",
                    },
                    "requester": {
                        "external_ref": "customer-demo",
                        "customer_tier": "standard",
                    },
                    "subject": "如何给团队配置消息通知",
                    "body": "请指导管理员配置企业通知。",
                    "locale": "zh-CN",
                    "attachments": [],
                    "metadata": {"product": "admin_portal"},
                },
            )
            created.raise_for_status()
            ticket_id = created.json()["id"]
            before = client.get(
                f"/api/v1/tickets/{ticket_id}",
                headers=agent,
            ).json()

            review = client.post(
                f"/api/v1/tickets/{ticket_id}/reviews",
                headers=agent,
                json={
                    "expected_version": before["version"],
                    "decision": "ACCEPTED",
                    "reason_code": "SMOKE_APPROVED",
                },
            )
            review.raise_for_status()
            final = client.get(
                f"/api/v1/tickets/{ticket_id}",
                headers=agent,
            ).json()
            metrics = client.get(
                "/api/v1/metrics/rag?business_unit_id=bu_demo",
                headers=auditor,
            ).json()

            print(
                json.dumps(
                    {
                        "knowledge": {
                            "status": published.json()["status"],
                            "chunks": published.json()["chunk_count"],
                        },
                        "ticket_before_review": {
                            "employee": before["employee"]["employee_key"],
                            "workflow": before["workflow_state"],
                            "category": before["classification"]["primary"],
                            "citations": len(before["draft"]["citations"]),
                            "claims": len(before["draft"]["claims"]),
                        },
                        "review_response": review.json()["workflow_state"],
                        "ticket_final": {
                            "workflow": final["workflow_state"],
                            "status": final["status"],
                            "sync": final["sync"]["status"],
                        },
                        "rag_metrics": {
                            "drafts": metrics["draft_count"],
                            "grounding_rate": metrics["grounding_rate"],
                            "claims": metrics["claim_count"],
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )


if __name__ == "__main__":
    main()


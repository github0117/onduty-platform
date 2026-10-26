from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ticket_agent.integrations import sync as ticket_sync_module
from ticket_agent.integrations.local import LocalTicketAdapter
from ticket_agent.integrations.types import TicketIntegrationError, TicketSyncResult
from ticket_agent.shared.db import SessionLocal
from ticket_agent.tickets.domain import TicketStatus, WorkflowState
from ticket_agent.tickets.models import AnswerDraft, Ticket
from ticket_agent.tools.models import ToolCall


def test_low_risk_ticket_reaches_pending_review(
    client: TestClient,
    ticket_payload: dict[str, object],
) -> None:
    response = client.post(
        "/api/v1/tickets",
        json=ticket_payload,
        headers={"Idempotency-Key": "source:HD-001"},
    )

    assert response.status_code == 202
    ticket_id = response.json()["id"]
    detail = client.get(f"/api/v1/tickets/{ticket_id}")

    assert detail.status_code == 200
    body = detail.json()
    assert body["workflow_state"] == "PENDING_REVIEW"
    assert body["status"] == "IN_PROGRESS"
    assert body["classification"]["primary"] == "product_howto"
    assert body["risk"]["level"] == "R0"
    assert body["routing"]["queue_id"] == "PRODUCT_SUPPORT"
    assert body["routing"]["needs_human"] is False
    assert body["draft"]["status"] == "NEEDS_REVIEW"
    assert "REVIEW_DRAFT" in body["allowed_actions"]


def test_high_risk_ticket_is_forced_to_human(
    client: TestClient,
    ticket_payload: dict[str, object],
) -> None:
    ticket_payload["subject"] = "账号被盗并发生数据泄露"
    ticket_payload["body"] = "我们发现账号被盗用，怀疑已经发生数据泄露，请立即处理。"
    response = client.post(
        "/api/v1/tickets",
        json=ticket_payload,
        headers={"Idempotency-Key": "source:HD-002"},
    )
    ticket_id = response.json()["id"]
    body = client.get(f"/api/v1/tickets/{ticket_id}").json()

    assert body["workflow_state"] == "NEEDS_HUMAN"
    assert body["status"] == "WAITING_HUMAN"
    assert body["risk"]["level"] == "R3"
    assert body["priority"]["level"] == "P0"
    assert body["routing"]["queue_id"] == "SECURITY_RESPONSE"
    assert body["routing"]["needs_human"] is True
    assert body["routing"]["human_reason"] == "HIGH_RISK_TOPIC"
    assert body["draft"] is None


def test_idempotent_create_returns_same_ticket(
    client: TestClient,
    ticket_payload: dict[str, object],
) -> None:
    headers = {"Idempotency-Key": "source:HD-003"}
    first = client.post("/api/v1/tickets", json=ticket_payload, headers=headers)
    second = client.post("/api/v1/tickets", json=ticket_payload, headers=headers)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    UUID(first.json()["id"])


def test_idempotency_conflict_for_different_body(
    client: TestClient,
    ticket_payload: dict[str, object],
) -> None:
    headers = {"Idempotency-Key": "source:HD-004"}
    first = client.post("/api/v1/tickets", json=ticket_payload, headers=headers)
    ticket_payload["subject"] = "另一个问题"
    second = client.post("/api/v1/tickets", json=ticket_payload, headers=headers)

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["code"] == "IDEMPOTENCY_CONFLICT"


def test_review_accepts_draft_and_completes_ticket(
    client: TestClient,
    ticket_payload: dict[str, object],
) -> None:
    created = client.post(
        "/api/v1/tickets",
        json=ticket_payload,
        headers={"Idempotency-Key": "source:HD-005"},
    )
    ticket_id = created.json()["id"]
    detail = client.get(f"/api/v1/tickets/{ticket_id}").json()

    review = client.post(
        f"/api/v1/tickets/{ticket_id}/reviews",
        json={
            "expected_version": detail["version"],
            "decision": "ACCEPTED",
            "reason_code": "AGENT_APPROVED",
        },
    )

    assert review.status_code == 200
    assert review.json()["workflow_state"] == "SYNCING"
    after = client.get(f"/api/v1/tickets/{ticket_id}").json()
    assert after["status"] == "RESOLVED"
    assert after["draft"]["status"] == "ACCEPTED"
    assert after["sync"]["status"] == "SUCCEEDED"
    assert after["sync"]["external_request_id"]


def test_human_edit_creates_feedback_and_repair_task(
    client: TestClient,
    ticket_payload: dict[str, object],
) -> None:
    created = client.post(
        "/api/v1/tickets",
        json=ticket_payload,
        headers={"Idempotency-Key": "source:HD-EDIT-FEEDBACK"},
    )
    ticket_id = created.json()["id"]
    detail = client.get(f"/api/v1/tickets/{ticket_id}").json()
    reviewed = client.post(
        f"/api/v1/tickets/{ticket_id}/reviews",
        json={
            "expected_version": detail["version"],
            "decision": "EDITED_AND_ACCEPTED",
            "edited_text": "管理员请进入设置中心重新配置通知。",
            "reason_code": "AGENT_CORRECTED",
        },
    )
    assert reviewed.status_code == 200, reviewed.text

    feedback = client.get(
        "/api/v1/knowledge/feedback?business_unit_id=bu_demo",
        headers={"X-Actor-Id": "agent-1"},
    )
    assert feedback.status_code == 200
    assert feedback.json()["total"] == 1
    item = feedback.json()["items"][0]
    assert item["reason_code"] == "HUMAN_EDITED"
    assert item["ticket_id"] == ticket_id
    assert item["repair_task_id"]

    repairs = client.get(
        "/api/v1/knowledge/repair-tasks?business_unit_id=bu_demo&status=OPEN",
        headers={"X-Actor-Id": "agent-1"},
    )
    assert repairs.status_code == 200
    assert repairs.json()["total"] == 1


def test_takeover_stops_automatic_processing(
    client: TestClient,
    ticket_payload: dict[str, object],
) -> None:
    created = client.post(
        "/api/v1/tickets",
        json=ticket_payload,
        headers={"Idempotency-Key": "source:HD-006"},
    )
    ticket_id = created.json()["id"]
    detail = client.get(f"/api/v1/tickets/{ticket_id}").json()

    takeover = client.post(
        f"/api/v1/tickets/{ticket_id}/takeover",
        json={
            "expected_version": detail["version"],
            "reason_code": "AGENT_REQUESTED",
        },
    )
    assert takeover.status_code == 200
    assert takeover.json()["workflow_state"] == "TAKEN_OVER"

    from ticket_agent.workers.process_ticket import process_ticket_job

    process_ticket_job(UUID(ticket_id), "test-correlation")
    after = client.get(f"/api/v1/tickets/{ticket_id}").json()
    assert after["workflow_state"] == "TAKEN_OVER"


def test_stale_version_is_rejected(
    client: TestClient,
    ticket_payload: dict[str, object],
) -> None:
    created = client.post(
        "/api/v1/tickets",
        json=ticket_payload,
        headers={"Idempotency-Key": "source:HD-007"},
    )
    ticket_id = created.json()["id"]

    response = client.post(
        f"/api/v1/tickets/{ticket_id}/takeover",
        json={"expected_version": 1, "reason_code": "AGENT_REQUESTED"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "VERSION_CONFLICT"


def test_ticket_list_returns_processed_ticket(
    client: TestClient,
    ticket_payload: dict[str, object],
) -> None:
    client.post(
        "/api/v1/tickets",
        json=ticket_payload,
        headers={"Idempotency-Key": "source:HD-008"},
    )
    response = client.get("/api/v1/tickets?business_unit_id=bu_demo")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["category_primary"] == "product_howto"


def test_test_ticket_archive_hides_closed_ticket_from_default_queue(
    client: TestClient,
    ticket_payload: dict[str, object],
) -> None:
    created = client.post(
        "/api/v1/tickets",
        json=ticket_payload,
        headers={"Idempotency-Key": "source:HD-ARCHIVE-001"},
    )
    ticket_id = created.json()["id"]

    archived = client.post(
        f"/api/v1/tickets/{ticket_id}/archive-test-data",
        headers={
            "X-Actor-Id": "test-admin",
            "X-Actor-Role": "admin",
        },
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "CLOSED"

    default_queue = client.get("/api/v1/tickets?business_unit_id=bu_demo")
    assert default_queue.status_code == 200
    assert default_queue.json()["total"] == 0

    full_history = client.get(
        "/api/v1/tickets?business_unit_id=bu_demo&include_closed=true"
    )
    assert full_history.status_code == 200
    assert full_history.json()["total"] == 1
    assert full_history.json()["items"][0]["status"] == "CLOSED"


def test_external_sync_terminal_failure_returns_ticket_to_human(
    client: TestClient,
    ticket_payload: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingAdapter:
        name = "failing"

        def get_sync_result(self, *, external_ticket_id: str, idempotency_key: str) -> object:
            del external_ticket_id, idempotency_key
            return None

        def sync_ticket(self, *, payload: object, idempotency_key: str) -> object:
            del payload, idempotency_key
            raise TicketIntegrationError("permanent API error", retryable=False)

    monkeypatch.setattr(
        ticket_sync_module,
        "get_ticket_adapter",
        lambda: FailingAdapter(),
    )
    created = client.post(
        "/api/v1/tickets",
        json=ticket_payload,
        headers={"Idempotency-Key": "source:SYNC-FAIL-001"},
    )
    ticket_id = created.json()["id"]
    detail = client.get(f"/api/v1/tickets/{ticket_id}").json()
    reviewed = client.post(
        f"/api/v1/tickets/{ticket_id}/reviews",
        json={
            "expected_version": detail["version"],
            "decision": "ACCEPTED",
            "reason_code": "AGENT_APPROVED",
        },
    )

    assert reviewed.status_code == 200
    after = client.get(f"/api/v1/tickets/{ticket_id}").json()
    assert after["workflow_state"] == "NEEDS_HUMAN"
    assert after["sync"]["status"] == "FAILED"
    assert after["sync"]["attempts"] == 1

    monkeypatch.setattr(
        ticket_sync_module,
        "get_ticket_adapter",
        lambda: LocalTicketAdapter(),
    )
    retried = client.post(
        f"/api/v1/tickets/{ticket_id}/sync-attempts",
        json={
            "expected_version": after["version"],
            "reason_code": "MANUAL_SYNC_RETRY",
        },
    )
    assert retried.status_code == 202
    final = client.get(f"/api/v1/tickets/{ticket_id}").json()
    assert final["workflow_state"] == "COMPLETED"
    assert final["sync"]["status"] == "SUCCEEDED"


def test_sync_preflight_reuses_existing_external_result(
    client: TestClient,
    ticket_payload: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExistingResultAdapter:
        name = "existing-result"
        write_called = False

        def get_sync_result(
            self,
            *,
            external_ticket_id: str,
            idempotency_key: str,
        ) -> TicketSyncResult:
            del external_ticket_id, idempotency_key
            return TicketSyncResult(external_request_id="existing-result-123")

        def sync_ticket(self, *, payload: object, idempotency_key: str) -> object:
            del payload, idempotency_key
            self.write_called = True
            raise AssertionError("Duplicate external write should not occur")

    adapter = ExistingResultAdapter()
    monkeypatch.setattr(
        ticket_sync_module,
        "get_ticket_adapter",
        lambda: adapter,
    )
    created = client.post(
        "/api/v1/tickets",
        json=ticket_payload,
        headers={"Idempotency-Key": "source:SYNC-PREFLIGHT-001"},
    )
    ticket_id = created.json()["id"]
    detail = client.get(f"/api/v1/tickets/{ticket_id}").json()
    client.post(
        f"/api/v1/tickets/{ticket_id}/reviews",
        json={
            "expected_version": detail["version"],
            "decision": "ACCEPTED",
            "reason_code": "AGENT_APPROVED",
        },
    )

    after = client.get(f"/api/v1/tickets/{ticket_id}").json()
    assert after["workflow_state"] == "COMPLETED"
    assert after["sync"]["external_request_id"] == "existing-result-123"
    assert adapter.write_called is False


def test_batch_sync_retry_and_metrics_alerts(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with SessionLocal() as session:
        ticket = Ticket(
            business_unit_id="bu_demo",
            source_system="batch_test",
            source_ticket_id=str(uuid4()),
            source_channel="test",
            idempotency_key=f"batch:{uuid4()}",
            request_hash="d" * 64,
            requester_ref="customer-batch",
            customer_tier="standard",
            subject="配置通知",
            body="请指导配置通知。",
            status=TicketStatus.WAITING_HUMAN,
            workflow_state=WorkflowState.NEEDS_HUMAN,
            category_primary="product_howto",
            category_secondary="configuration",
            priority="P3",
            risk_level="R0",
            queue_id="PRODUCT_SUPPORT",
            needs_human=True,
            human_reason="EXTERNAL_SYNC_FAILED",
            sync_status="FAILED",
            sync_attempts=5,
            sync_error="permanent",
            version=5,
        )
        session.add(ticket)
        session.flush()
        session.add(
            AnswerDraft(
                ticket_id=ticket.id,
                text="请进入设置中心配置通知。",
                status="ACCEPTED",
                citations_json=[],
                claims_json=[],
                grounding_status="NO_KNOWLEDGE",
            )
        )
        session.add(
            Ticket(
                business_unit_id="bu_demo",
                source_system="batch_test",
                source_ticket_id=str(uuid4()),
                source_channel="test",
                idempotency_key=f"batch-failed:{uuid4()}",
                request_hash="e" * 64,
                requester_ref="customer-failed",
                customer_tier="standard",
                subject="同步失败工单",
                body="用于验证同步失败指标。",
                status=TicketStatus.WAITING_HUMAN,
                workflow_state=WorkflowState.NEEDS_HUMAN,
                needs_human=True,
                human_reason="EXTERNAL_SYNC_FAILED",
                sync_status="FAILED",
                sync_attempts=5,
                sync_error="permanent",
                version=3,
            )
        )
        session.commit()
        ticket_id = ticket.id

    monkeypatch.setattr(
        ticket_sync_module,
        "get_ticket_adapter",
        lambda: LocalTicketAdapter(),
    )
    response = client.post(
        "/api/v1/tickets/sync-attempts:batch",
        headers={"X-Actor-Id": "supervisor-1", "X-Actor-Role": "supervisor"},
        json={
            "ticket_ids": [str(ticket_id), str(ticket_id)],
            "reason_code": "BATCH_SYNC_RETRY",
        },
    )

    assert response.status_code == 202
    codes = [item["code"] for item in response.json()["items"]]
    assert codes == ["QUEUED", "DUPLICATE"]
    after = client.get(f"/api/v1/tickets/{ticket_id}").json()
    assert after["workflow_state"] == "COMPLETED"

    metrics = client.get(
        "/api/v1/metrics/sync?business_unit_id=bu_demo",
        headers={"X-Actor-Id": "auditor-1", "X-Actor-Role": "auditor"},
    )
    assert metrics.status_code == 200
    assert metrics.json()["attempted"] >= 1
    assert metrics.json()["succeeded"] >= 1
    assert metrics.json()["failure_rate"] > 0
    assert "SYNC_FAILURE_RATE_HIGH" in metrics.json()["alerts"]


def test_prometheus_endpoint_exposes_sync_and_rag_metrics(
    client: TestClient,
) -> None:
    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "ticket_worker_sync_attempted" in response.text
    assert "ticket_worker_rag_grounding_rate" in response.text
    assert "ticket_worker_tool_p95_duration_ms" in response.text
    assert "ticket_worker_model_total_tokens" in response.text
    assert "ticket_worker_model_denied" in response.text
    assert "ticket_worker_model_budget_forecast_alerts" in response.text


def test_ticket_loop_records_tool_calls(
    client: TestClient,
    ticket_payload: dict[str, object],
) -> None:
    created = client.post(
        "/api/v1/tickets",
        json=ticket_payload,
        headers={"Idempotency-Key": "source:TOOL-CALLS"},
    )
    ticket_id = created.json()["id"]
    detail = client.get(f"/api/v1/tickets/{ticket_id}").json()
    client.post(
        f"/api/v1/tickets/{ticket_id}/reviews",
        json={
            "expected_version": detail["version"],
            "decision": "ACCEPTED",
            "reason_code": "TOOL_AUDIT_TEST",
        },
    )

    with SessionLocal() as session:
        calls = session.scalars(
            select(ToolCall).where(ToolCall.ticket_id == UUID(ticket_id))
        ).all()

    tool_keys = {call.tool_key for call in calls}
    assert {"ticket.read", "knowledge.search", "draft.create", "ticket.sync"} <= tool_keys
    assert all(call.status == "SUCCEEDED" for call in calls)
    sync_call = next(call for call in calls if call.tool_key == "ticket.sync")
    assert sync_call.risk_level == "R2"

    audit_headers = {
        "X-Actor-Id": "auditor-tools",
        "X-Actor-Role": "auditor",
    }
    listed = client.get(
        f"/api/v1/tool-calls?ticket_id={ticket_id}",
        headers=audit_headers,
    )
    metrics = client.get(
        "/api/v1/metrics/tools?business_unit_id=bu_demo",
        headers=audit_headers,
    )

    assert listed.status_code == 200
    assert listed.json()["total"] >= 4
    assert {item["tool_key"] for item in listed.json()["items"]} >= {
        "ticket.read",
        "knowledge.search",
        "draft.create",
        "ticket.sync",
    }
    assert metrics.status_code == 200
    assert metrics.json()["calls"] >= 4
    assert metrics.json()["success_rate"] == 1.0
    assert metrics.json()["average_duration_ms"] >= 0


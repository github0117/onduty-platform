from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ticket_agent.shared.db import SessionLocal, system_session
from ticket_agent.workflows.domain import StepStatus, WorkflowStatus
from ticket_agent.workflows.models import WorkflowRun, WorkflowStep
from ticket_agent.workflows.service import (
    StepSpec,
    ensure_ticket_sync_run,
    execute_workflow_run,
    reclaim_stuck_steps,
    start_run,
)
from ticket_agent.workflows.steps import STEP_HANDLERS, StepNonRetryableError

ADMIN = {"X-Actor-Id": "workflow-admin", "X-Actor-Role": "admin"}
AUDITOR = {"X-Actor-Id": "workflow-auditor", "X-Actor-Role": "auditor"}
AGENT = {"X-Actor-Id": "workflow-agent", "X-Actor-Role": "agent"}


def create_ticket(client: TestClient, external_ticket_id: str) -> UUID:
    payload = {
        "business_unit_id": "bu_demo",
        "source": {
            "system": "demo_helpdesk",
            "channel": "web_form",
            "external_ticket_id": external_ticket_id,
        },
        "requester": {"external_ref": "customer_wf", "customer_tier": "standard"},
        "subject": "工作流测试工单",
        "body": "请确认外部同步流程可以重试。",
        "locale": "zh-CN",
        "attachments": [],
        "metadata": {"product": "admin_portal"},
    }
    response = client.post(
        "/api/v1/tickets",
        json=payload,
        headers={"Idempotency-Key": f"source:{external_ticket_id}"},
    )
    assert response.status_code == 202, response.text
    return UUID(response.json()["id"])


@pytest.fixture(autouse=True)
def restore_step_registry() -> Any:
    original = dict(STEP_HANDLERS)
    yield
    STEP_HANDLERS.clear()
    STEP_HANDLERS.update(original)


def register_fake_step(workflow_type: str, name: str, handler: Any) -> None:
    STEP_HANDLERS[(workflow_type, name)] = handler


def test_duplicate_outbox_handoff_reuses_one_run(client: TestClient) -> None:
    ticket_id = create_ticket(client, external_ticket_id="WF-DUP-1")
    event_id = uuid4()

    with SessionLocal() as session:
        first, created_first = ensure_ticket_sync_run(
            session,
            ticket_id=ticket_id,
            correlation_id="corr-1",
            outbox_event_id=event_id,
        )
        session.commit()
        second, created_second = ensure_ticket_sync_run(
            session,
            ticket_id=ticket_id,
            correlation_id="corr-1",
            outbox_event_id=event_id,
        )
        session.commit()

    assert created_first is True
    assert created_second is False
    assert first == second


def test_manual_retry_creates_a_new_run(client: TestClient) -> None:
    ticket_id = create_ticket(client, external_ticket_id="WF-RETRY-1")
    with SessionLocal() as session:
        first, _ = ensure_ticket_sync_run(
            session,
            ticket_id=ticket_id,
            correlation_id="corr-1",
            outbox_event_id=uuid4(),
        )
        session.commit()
        second, _ = ensure_ticket_sync_run(
            session,
            ticket_id=ticket_id,
            correlation_id="corr-2",
            outbox_event_id=uuid4(),
        )
        session.commit()

    assert first != second


def test_all_steps_succeed_and_run_is_terminal() -> None:
    seen: list[str] = []

    def first(_context: Any) -> dict[str, Any]:
        seen.append("first")
        return {"ok": True}

    def second(_context: Any) -> dict[str, Any]:
        seen.append("second")
        return {"ok": True}

    register_fake_step("wf_test", "first", first)
    register_fake_step("wf_test", "second", second)
    with SessionLocal() as session:
        run, _ = start_run(
            session,
            business_unit_id="bu_demo",
            workflow_type="wf_test",
            aggregate_type="ticket",
            aggregate_id=uuid4(),
            idempotency_key=f"wf_test:{uuid4()}",
            steps=[StepSpec("first"), StepSpec("second")],
        )
        session.commit()

    execute_workflow_run(run.id)

    with SessionLocal() as session:
        stored = session.get(WorkflowRun, run.id)
        assert stored is not None
        assert stored.status == WorkflowStatus.SUCCEEDED.value
        steps = session.scalars(
            select(WorkflowStep).where(WorkflowStep.workflow_run_id == run.id)
        ).all()
    assert [step.status for step in steps] == [
        StepStatus.SUCCEEDED.value,
        StepStatus.SUCCEEDED.value,
    ]
    assert seen == ["first", "second"]


def test_step_failure_dead_letters_then_replay_resets(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_context: Any) -> dict[str, Any]:
        raise StepNonRetryableError("SYNC_REJECTED: upstream says no")

    register_fake_step("wf_test", "explode", handler)
    with SessionLocal() as session:
        run, created = start_run(
            session,
            business_unit_id="bu_demo",
            workflow_type="wf_test",
            aggregate_type="ticket",
            aggregate_id=uuid4(),
            idempotency_key="wf_test:boom",
            steps=[StepSpec("explode", max_attempts=2)],
            context={"correlation_id": "corr-boom"},
        )
        session.commit()

    assert created is True
    execute_workflow_run(run.id)

    with SessionLocal() as session:
        stored = session.get(WorkflowRun, run.id)
        assert stored is not None
        assert stored.status == WorkflowStatus.DEAD_LETTER.value
        step = session.scalar(
            select(WorkflowStep).where(WorkflowStep.workflow_run_id == run.id)
        )
        assert step is not None
        assert step.status == StepStatus.DEAD_LETTER.value
        assert step.attempt_count == 1
        assert "SYNC_REJECTED" in (step.last_error or "")

    dead_letters = client.get(
        "/api/v1/workflows/dead-letters",
        headers=AUDITOR,
    )
    assert dead_letters.status_code == 200
    assert len(dead_letters.json()["items"]) == 1

    denied = client.post(
        f"/api/v1/workflows/runs/{run.id}/replay",
        headers=AUDITOR,
    )
    assert denied.status_code == 403

    # Replay must not execute inline inside this request; the point is the
    # state reset plus the audit row.
    monkeypatch.setattr(
        "ticket_agent.workflows.service.dispatch_workflow_run",
        lambda _run_id: None,
    )
    replayed = client.post(
        f"/api/v1/workflows/runs/{run.id}/replay",
        headers=ADMIN,
    )
    assert replayed.status_code == 202
    assert replayed.json()["accepted"] is True
    body = replayed.json()["run"]
    assert body["status"] == WorkflowStatus.PENDING.value
    assert body["steps"][0]["status"] == StepStatus.PENDING.value
    assert body["steps"][0]["attempt_count"] == 0
    assert body["steps"][0]["last_error"] is None

    run_detail = client.get(
        f"/api/v1/workflows/runs/{run.id}",
        headers=ADMIN,
    )
    assert run_detail.status_code == 200


def test_replay_rejects_succeeded_run(client: TestClient) -> None:
    with SessionLocal() as session:
        run, _ = start_run(
            session,
            business_unit_id="bu_demo",
            workflow_type="wf_test",
            aggregate_type="ticket",
            aggregate_id=uuid4(),
            idempotency_key=f"wf_test:{uuid4()}",
            steps=[StepSpec("noop")],
        )
        run.status = WorkflowStatus.SUCCEEDED.value
        session.commit()

    response = client.post(
        f"/api/v1/workflows/runs/{run.id}/replay",
        headers=ADMIN,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "WORKFLOW_NOT_REPLAYABLE"


def test_agent_cannot_read_or_replay_workflows(client: TestClient) -> None:
    assert client.get("/api/v1/workflows/runs", headers=AGENT).status_code == 403
    assert (
        client.get("/api/v1/workflows/dead-letters", headers=AGENT).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/workflows/runs/{uuid4()}/replay",
            headers=AGENT,
        ).status_code
        == 403
    )


def test_runs_are_tenant_scoped(client: TestClient) -> None:
    with SessionLocal() as session:
        run, _ = start_run(
            session,
            business_unit_id="bu_other",
            workflow_type="wf_test",
            aggregate_type="ticket",
            aggregate_id=uuid4(),
            idempotency_key=f"wf_test:{uuid4()}",
            steps=[StepSpec("noop")],
        )
        session.commit()

    own = client.get("/api/v1/workflows/runs", headers=AUDITOR)
    assert own.status_code == 200
    assert all(item["business_unit_id"] != "bu_other" for item in own.json()["items"])

    denied = client.get(
        f"/api/v1/workflows/runs/{run.id}",
        headers=AUDITOR,
    )
    assert denied.status_code == 403


def test_expired_lease_is_reclaimed_without_consuming_an_attempt() -> None:
    with SessionLocal() as session:
        run, _ = start_run(
            session,
            business_unit_id="bu_demo",
            workflow_type="wf_test",
            aggregate_type="ticket",
            aggregate_id=uuid4(),
            idempotency_key=f"wf_test:{uuid4()}",
            steps=[StepSpec("noop")],
        )
        step = session.scalar(
            select(WorkflowStep).where(WorkflowStep.workflow_run_id == run.id)
        )
        assert step is not None
        step.status = StepStatus.RUNNING.value
        step.attempt_count = 1
        step.lease_expires_at = datetime.now(UTC) - timedelta(seconds=5)
        run.status = WorkflowStatus.RUNNING.value
        session.commit()

    reclaimed = reclaim_stuck_steps()
    assert run.id in reclaimed

    with SessionLocal() as session:
        step = session.scalar(
            select(WorkflowStep).where(WorkflowStep.workflow_run_id == run.id)
        )
        assert step is not None
        assert step.status == StepStatus.PENDING.value
        assert step.attempt_count == 1
        assert step.lease_expires_at is None
        assert step.last_error == "WORKFLOW_STEP_LEASE_EXPIRED"
        stored_run = session.get(WorkflowRun, run.id)
        assert stored_run is not None
        assert stored_run.status == WorkflowStatus.PENDING.value


def test_metrics_endpoint_reports_workflow_gauges(client: TestClient) -> None:
    with SessionLocal() as session:
        start_run(
            session,
            business_unit_id="bu_demo",
            workflow_type="wf_test",
            aggregate_type="ticket",
            aggregate_id=uuid4(),
            idempotency_key=f"wf_test:{uuid4()}",
            steps=[StepSpec("noop")],
        )
        session.commit()

    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.text
    assert "ticket_worker_workflow_runs" in body
    assert "ticket_worker_workflow_dead_letter_runs" in body
    assert "ticket_worker_workflow_steps_due" in body


def test_notify_step_writes_one_notification_per_run(client: TestClient) -> None:
    from ticket_agent.tickets.models import AuditEvent
    from ticket_agent.workflows.steps import WorkflowContext, notify

    ticket_id = create_ticket(client, external_ticket_id="WF-NOTIFY-1")
    context = WorkflowContext(
        run_id=uuid4(),
        step_id=uuid4(),
        business_unit_id="bu_demo",
        workflow_type="ticket_sync",
        step_name="notify",
        attempt=1,
        context={"ticket_id": str(ticket_id), "correlation_id": "corr-notify"},
    )
    first = notify(context)
    second = notify(context)

    assert first["deduplicated"] is False
    assert second["deduplicated"] is True
    with SessionLocal() as session:
        rows = session.scalars(
            select(AuditEvent).where(AuditEvent.event_type == "workflow.notified")
        ).all()
    assert len(rows) == 1


def test_business_unit_of_run_is_preserved(client: TestClient) -> None:
    ticket_id = create_ticket(client, external_ticket_id="WF-UNIT-1")
    with system_session() as session:
        run_id, _ = ensure_ticket_sync_run(
            session,
            ticket_id=ticket_id,
            correlation_id="corr-unit",
        )
        session.commit()
    with SessionLocal() as session:
        run = session.get(WorkflowRun, run_id)
        assert run is not None
        assert run.business_unit_id == "bu_demo"

from fastapi.testclient import TestClient


def test_ticket_processing_creates_run_and_trace(
    client: TestClient,
    ticket_payload: dict[str, object],
) -> None:
    created = client.post(
        "/api/v1/tickets",
        json=ticket_payload,
        headers={
            "X-Actor-Id": "agent-run-test",
            "X-Actor-Role": "agent",
            "Idempotency-Key": "agent-run:test:001",
        },
    )
    assert created.status_code == 202, created.text
    ticket_id = created.json()["id"]

    response = client.get(
        f"/api/v1/agent-runs?ticket_id={ticket_id}",
        headers={"X-Actor-Id": "auditor-run", "X-Actor-Role": "auditor"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 1
    run = payload["items"][0]
    assert run["ticket_id"] == ticket_id
    assert run["run_type"] == "ticket_processing"
    assert run["status"] in {"SUCCEEDED", "WAITING_HUMAN"}
    assert run["duration_ms"] is not None

    trace = client.get(
        f"/api/v1/agent-runs/{run['id']}/trace",
        headers={"X-Actor-Id": "auditor-run", "X-Actor-Role": "auditor"},
    )

    assert trace.status_code == 200, trace.text
    events = trace.json()["events"]
    event_types = {event["event_type"] for event in events}
    assert {"run", "workflow", "tool", "audit"} <= event_types
    assert any(
        event["title"] == "ticket.read" and event["status"] == "SUCCEEDED"
        for event in events
    )

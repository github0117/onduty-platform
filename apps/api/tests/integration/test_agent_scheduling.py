"""End-to-end acceptance for shift templates, rosters and schedule gating."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ticket_agent.customer_service.models import (
    AgentPresence,
    CustomerConversation,
)
from ticket_agent.scheduling import service as scheduling_service
from ticket_agent.scheduling.models import (
    AgentRoster,
    AgentRosterEntry,
    AgentSchedulingPolicy,
    AgentShiftTemplate,
)
from ticket_agent.shared.db import system_session
from ticket_agent.tickets.models import AuditEvent, Ticket


@pytest.fixture()
def bu() -> str:
    return f"bu_sched_{uuid4().hex[:8]}"


def _admin(bu: str) -> dict[str, str]:
    return {
        "X-Actor-Id": "sched-admin",
        "X-Actor-Role": "admin",
        "X-Business-Unit-Id": bu,
    }


def _agent_headers(agent_id: str, bu: str) -> dict[str, str]:
    return {
        "X-Actor-Id": agent_id,
        "X-Actor-Role": "agent",
        "X-Business-Unit-Id": bu,
    }


def _current_week_start() -> date:
    local = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    return local - timedelta(days=local.weekday())


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _heartbeat(
    client: TestClient,
    agent_id: str,
    bu: str,
    *,
    max_conversations: int = 5,
    auto_assign_enabled: bool = True,
) -> None:
    response = client.post(
        "/api/v1/customer-service/presence/heartbeat",
        headers=_agent_headers(agent_id, bu),
        json={
            "display_name": agent_id,
            "status": "ONLINE",
            "business_unit_id": bu,
            "skills": ["ecommerce_aftersales"],
            "risk_clearance": "R2",
            "max_conversations": max_conversations,
            "auto_assign_enabled": auto_assign_enabled,
        },
    )
    assert response.status_code == 200, response.text


def _create_shift(
    client: TestClient,
    bu: str,
    *,
    name: str,
    start_local: str = "00:00",
    end_local: str = "23:59",
) -> dict[str, object]:
    response = client.post(
        "/api/v1/scheduling/shifts",
        headers=_admin(bu),
        json={
            "name": name,
            "start_local": start_local,
            "end_local": end_local,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_draft(
    client: TestClient,
    bu: str,
    week_start: date,
    *,
    timezone: str = "Asia/Shanghai",
) -> dict[str, object]:
    response = client.post(
        "/api/v1/scheduling/rosters",
        headers=_admin(bu),
        json={"week_start": week_start.isoformat(), "timezone": timezone},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _week_entries(
    week_start: date,
    shift_id: str,
    agent_ids: list[str],
) -> list[dict[str, str]]:
    return [
        {
            "agent_id": agent_id,
            "shift_template_id": shift_id,
            "shift_date": (week_start + timedelta(days=offset)).isoformat(),
        }
        for agent_id in agent_ids
        for offset in range(7)
    ]


def _save(
    client: TestClient,
    bu: str,
    roster: dict[str, object],
    entries: list[dict[str, str]],
    *,
    version: int | None = None,
):
    return client.put(
        f"/api/v1/scheduling/rosters/{roster['id']}/draft",
        headers=_admin(bu),
        json={
            "version": roster["version"] if version is None else version,
            "entries": entries,
        },
    )


def _publish(
    client: TestClient,
    bu: str,
    roster: dict[str, object],
):
    return client.post(
        f"/api/v1/scheduling/rosters/{roster['id']}/publish",
        headers=_admin(bu),
    )


def _enable_policy(client: TestClient, bu: str, enabled: bool = True):
    return client.put(
        "/api/v1/scheduling/policy",
        headers=_admin(bu),
        json={"enforce_published_schedule": enabled},
    )


def _seed_waiting_conversation(bu: str) -> str:
    ticket_id = uuid4()
    conversation_id = uuid4()
    with system_session() as session:
        session.add(
            Ticket(
                id=ticket_id,
                business_unit_id=bu,
                source_system="agent_scheduling_test",
                source_ticket_id=f"ticket-{ticket_id}",
                source_channel="web_form",
                idempotency_key=f"idem-{ticket_id}",
                request_hash="0" * 64,
                requester_ref=f"buyer-{ticket_id}",
                subject="排班派单验证",
                body="需要人工处理",
                workflow_state="NEEDS_HUMAN",
                priority="P2",
                risk_level="R0",
                needs_human=True,
            )
        )
        session.add(
            CustomerConversation(
                id=conversation_id,
                business_unit_id=bu,
                requester_ref=f"buyer-{ticket_id}",
                channel="web_form",
                status="ACTIVE",
                current_ticket_id=ticket_id,
            )
        )
        session.commit()
    return str(conversation_id)


def test_shift_template_lifecycle_and_conflicts(
    client: TestClient,
    bu: str,
) -> None:
    shift = _create_shift(client, bu, name="排班白班")
    assert shift["cross_day"] is False
    assert shift["version"] == 1

    duplicate = client.post(
        "/api/v1/scheduling/shifts",
        headers=_admin(bu),
        json={
            "name": "排班白班",
            "start_local": "08:00",
            "end_local": "17:00",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "SHIFT_NAME_CONFLICT"

    same_time = client.post(
        "/api/v1/scheduling/shifts",
        headers=_admin(bu),
        json={
            "name": "排班零宽班",
            "start_local": "09:00",
            "end_local": "09:00",
        },
    )
    assert same_time.status_code == 422
    assert same_time.json()["code"] == "INVALID_SHIFT_TIME"

    night = _create_shift(
        client,
        bu,
        name="排班夜班",
        start_local="22:00",
        end_local="06:00",
    )
    assert night["cross_day"] is True

    listed = client.get("/api/v1/scheduling/shifts", headers=_admin(bu))
    assert listed.status_code == 200
    assert {item["name"] for item in listed.json()["items"]} >= {
        "排班白班",
        "排班夜班",
    }

    updated = client.patch(
        f"/api/v1/scheduling/shifts/{shift['id']}",
        headers=_admin(bu),
        json={
            "name": "排班白班改",
            "start_local": "07:00",
            "end_local": "16:00",
            "version": shift["version"],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    assert updated.json()["start_local"].startswith("07:00")

    stale = client.patch(
        f"/api/v1/scheduling/shifts/{shift['id']}",
        headers=_admin(bu),
        json={"name": "排班白班再改", "version": 1},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "SHIFT_VERSION_CONFLICT"

    archived = client.patch(
        f"/api/v1/scheduling/shifts/{night['id']}",
        headers=_admin(bu),
        json={"status": "ARCHIVED", "version": night["version"]},
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "ARCHIVED"


def test_draft_validation_versioning_and_idempotent_save(
    client: TestClient,
    bu: str,
) -> None:
    week_start = _current_week_start()
    _heartbeat(client, "sched-agent-a", bu)
    _heartbeat(client, "sched-agent-b", bu)
    shift = _create_shift(client, bu, name="排班校验班")

    not_monday = client.post(
        "/api/v1/scheduling/rosters",
        headers=_admin(bu),
        json={
            "week_start": (week_start + timedelta(days=1)).isoformat(),
            "timezone": "Asia/Shanghai",
        },
    )
    assert not_monday.status_code == 422
    assert not_monday.json()["code"] == "INVALID_WEEK"

    bad_timezone = client.post(
        "/api/v1/scheduling/rosters",
        headers=_admin(bu),
        json={"week_start": week_start.isoformat(), "timezone": "Mars/Olympus"},
    )
    assert bad_timezone.status_code == 422
    assert bad_timezone.json()["code"] == "INVALID_SHIFT_TIME"

    draft = _create_draft(client, bu, week_start)
    again = _create_draft(client, bu, week_start)
    assert again["id"] == draft["id"]
    assert again["version"] == 1

    entries = _week_entries(week_start, str(shift["id"]), ["sched-agent-a"])
    saved = _save(client, bu, draft, entries)
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 2
    assert len(saved.json()["entries"]) == 7

    first_entry = saved.json()["entries"][0]
    expected_start = datetime.combine(
        date.fromisoformat(first_entry["shift_date"]),
        datetime.strptime("00:00", "%H:%M").time(),
        tzinfo=ZoneInfo("Asia/Shanghai"),
    ).astimezone(UTC)
    assert datetime.fromisoformat(first_entry["start_at"]) == expected_start
    assert first_entry["snapshot_json"]["timezone"] == "Asia/Shanghai"

    replayed = _save(client, bu, draft, entries, version=1)
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["version"] == 2
    saved_payload = saved.json()

    different = entries + _week_entries(
        week_start, str(shift["id"]), ["sched-agent-b"]
    )
    conflict = _save(client, bu, saved_payload, different, version=1)
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "ROSTER_VERSION_CONFLICT"

    duplicate_day = _save(
        client,
        bu,
        saved_payload,
        entries + [entries[0]],
        version=2,
    )
    assert duplicate_day.status_code == 422
    assert duplicate_day.json()["code"] == "INVALID_ROSTER_ENTRY"

    outside = _save(
        client,
        bu,
        saved_payload,
        [
            {
                "agent_id": "sched-agent-a",
                "shift_template_id": str(shift["id"]),
                "shift_date": (week_start + timedelta(days=8)).isoformat(),
            }
        ],
        version=2,
    )
    assert outside.status_code == 422
    assert outside.json()["code"] == "INVALID_ROSTER_ENTRY"

    unknown_agent = _save(
        client,
        bu,
        saved_payload,
        [
            {
                "agent_id": "missing-agent",
                "shift_template_id": str(shift["id"]),
                "shift_date": week_start.isoformat(),
            }
        ],
        version=2,
    )
    assert unknown_agent.status_code == 422
    assert unknown_agent.json()["code"] == "AGENT_NOT_FOUND"

    with system_session() as session:
        roster = session.get(AgentRoster, UUID(str(saved.json()["id"])))
        assert roster is not None
        stored = session.scalars(
            select(AgentRosterEntry).where(AgentRosterEntry.roster_id == roster.id)
        ).all()
        assert {entry.agent_id for entry in stored} == {"sched-agent-a"}


def test_publish_clone_and_archive_shift_snapshot(
    client: TestClient,
    bu: str,
) -> None:
    week_start = _current_week_start()
    _heartbeat(client, "sched-agent-a", bu)
    _heartbeat(client, "sched-agent-b", bu)
    shift = _create_shift(client, bu, name="排班发布班")
    draft = _create_draft(client, bu, week_start)

    empty = _publish(client, bu, draft)
    assert empty.status_code == 422
    assert empty.json()["code"] == "EMPTY_ROSTER"

    entries = _week_entries(
        week_start,
        str(shift["id"]),
        ["sched-agent-a", "sched-agent-b"],
    )
    saved_response = _save(client, bu, draft, entries)
    assert saved_response.status_code == 200, saved_response.text
    published = _publish(client, bu, saved_response.json())
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "PUBLISHED"
    assert published.json()["published_by"] == "sched-admin"

    repeated = _publish(client, bu, published.json())
    assert repeated.status_code == 200
    assert repeated.json()["id"] == published.json()["id"]

    archived_shift = client.patch(
        f"/api/v1/scheduling/shifts/{shift['id']}",
        headers=_admin(bu),
        json={"status": "ARCHIVED", "version": shift["version"]},
    )
    assert archived_shift.status_code == 200, archived_shift.text

    with system_session() as session:
        frozen = session.scalars(
            select(AgentRosterEntry).where(
                AgentRosterEntry.roster_id == UUID(str(published.json()["id"]))
            )
        ).all()
        assert len(frozen) == 14
        assert all(entry.shift_name == "排班发布班" for entry in frozen)
        assert all(
            entry.snapshot_json["shift_version"] == 1 for entry in frozen
        )

    cloned = client.post(
        f"/api/v1/scheduling/rosters/{published.json()['id']}/clone",
        headers=_admin(bu),
    )
    assert cloned.status_code == 200, cloned.text
    clone_payload = cloned.json()
    assert clone_payload["status"] == "DRAFT"
    assert clone_payload["cloned_from_roster_id"] == published.json()["id"]
    assert len(clone_payload["entries"]) == 14
    assert clone_payload["entries"][0]["snapshot_json"]["shift_name"] == (
        "排班发布班"
    )

    duplicate_draft = client.post(
        f"/api/v1/scheduling/rosters/{published.json()['id']}/clone",
        headers=_admin(bu),
    )
    assert duplicate_draft.status_code == 409
    assert duplicate_draft.json()["code"] == "ROSTER_DRAFT_EXISTS"

    republished = _publish(client, bu, clone_payload)
    assert republished.status_code == 200, republished.text
    assert republished.json()["status"] == "PUBLISHED"

    with system_session() as session:
        previous = session.get(AgentRoster, UUID(str(published.json()["id"])))
        assert previous is not None
        assert previous.status == "ARCHIVED"
        latest_entries = session.scalars(
            select(AgentRosterEntry).where(
                AgentRosterEntry.roster_id
                == UUID(str(republished.json()["id"]))
            )
        ).all()
        assert len(latest_entries) == 14
        assert all(
            entry.snapshot_json["shift_name"] == "排班发布班"
            for entry in latest_entries
        )


def test_archiving_shift_referenced_by_draft_is_rejected(
    client: TestClient,
    bu: str,
) -> None:
    week_start = _current_week_start()
    _heartbeat(client, "sched-agent-a", bu)
    shift = _create_shift(client, bu, name="排班占用班")
    draft = _create_draft(client, bu, week_start)
    assert _save(
        client,
        bu,
        draft,
        _week_entries(week_start, str(shift["id"]), ["sched-agent-a"]),
    ).status_code == 200

    blocked = client.patch(
        f"/api/v1/scheduling/shifts/{shift['id']}",
        headers=_admin(bu),
        json={"status": "ARCHIVED", "version": shift["version"]},
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "SHIFT_IN_USE"


def test_policy_requires_current_week_published_schedule(
    client: TestClient,
    bu: str,
) -> None:
    week_start = _current_week_start()
    _heartbeat(client, "sched-agent-a", bu)
    shift = _create_shift(client, bu, name="排班策略班")

    default_policy = client.get("/api/v1/scheduling/policy", headers=_admin(bu))
    assert default_policy.status_code == 200
    assert default_policy.json()["enforce_published_schedule"] is False
    assert default_policy.json()["persisted"] is False
    assert default_policy.json()["coverage_gap"] is True

    not_ready = _enable_policy(client, bu)
    assert not_ready.status_code == 422
    assert not_ready.json()["code"] == "SCHEDULE_NOT_READY"

    next_week = week_start + timedelta(days=7)
    other_week = _create_draft(client, bu, next_week)
    assert _save(
        client,
        bu,
        other_week,
        _week_entries(next_week, str(shift["id"]), ["sched-agent-a"]),
    ).status_code == 200
    assert _publish(client, bu, other_week).status_code == 200

    still_not_ready = _enable_policy(client, bu)
    assert still_not_ready.status_code == 422

    current = _create_draft(client, bu, week_start)
    assert _save(
        client,
        bu,
        current,
        _week_entries(week_start, str(shift["id"]), ["sched-agent-a"]),
    ).status_code == 200
    assert _publish(client, bu, current).status_code == 200

    enabled = _enable_policy(client, bu)
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["enforce_published_schedule"] is True
    assert enabled.json()["persisted"] is True
    assert enabled.json()["schedule_ready"] is True
    assert enabled.json()["coverage_gap"] is False

    disabled = _enable_policy(client, bu, False)
    assert disabled.status_code == 200
    assert disabled.json()["enforce_published_schedule"] is False


def test_on_duty_reports_shift_windows_and_gaps(
    client: TestClient,
    bu: str,
) -> None:
    week_start = _current_week_start()
    _heartbeat(client, "sched-on-duty-a", bu)
    _heartbeat(client, "sched-on-duty-off", bu)
    shift = _create_shift(client, bu, name="排班当班班")
    draft = _create_draft(client, bu, week_start)
    assert _save(
        client,
        bu,
        draft,
        _week_entries(week_start, str(shift["id"]), ["sched-on-duty-a"]),
    ).status_code == 200
    assert _publish(client, bu, draft).status_code == 200

    response = client.get("/api/v1/scheduling/on-duty", headers=_admin(bu))
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schedule_ready"] is True
    assert payload["coverage_gap"] is False
    by_agent = {item["agent_id"]: item for item in payload["items"]}
    assert by_agent["sched-on-duty-a"]["on_shift"] is True
    assert by_agent["sched-on-duty-a"]["shift_start_at"] is not None
    assert by_agent["sched-on-duty-off"]["on_shift"] is False
    assert "未在已发布班表当班" not in by_agent["sched-on-duty-off"][
        "excluded_reasons"
    ]

    enabled = _enable_policy(client, bu)
    assert enabled.status_code == 200, enabled.text

    enforced = client.get("/api/v1/scheduling/on-duty", headers=_admin(bu))
    assert enforced.status_code == 200
    enforced_by_agent = {
        item["agent_id"]: item for item in enforced.json()["items"]
    }
    assert enforced_by_agent["sched-on-duty-off"]["excluded_reasons"] == [
        "未在已发布班表当班"
    ]


def test_shift_window_includes_start_excludes_end(
    client: TestClient,
    bu: str,
) -> None:
    week_start = _current_week_start()
    _heartbeat(client, "sched-boundary-agent", bu)
    day_shift = _create_shift(
        client, bu, name="边界白班", start_local="09:00", end_local="18:00"
    )
    night_shift = _create_shift(
        client, bu, name="边界夜班", start_local="22:00", end_local="06:00"
    )
    draft = _create_draft(client, bu, week_start)
    entries = [
        {
            "agent_id": "sched-boundary-agent",
            "shift_template_id": str(day_shift["id"]),
            "shift_date": (week_start + timedelta(days=1)).isoformat(),
        },
        {
            "agent_id": "sched-boundary-agent",
            "shift_template_id": str(night_shift["id"]),
            "shift_date": (week_start + timedelta(days=2)).isoformat(),
        },
    ]
    assert _save(client, bu, draft, entries).status_code == 200
    assert _publish(client, bu, draft).status_code == 200

    with system_session() as session:
        rows = {
            row.shift_date: row
            for row in session.scalars(
                select(AgentRosterEntry).where(
                    AgentRosterEntry.roster_id == UUID(str(draft["id"]))
                )
            ).all()
        }
        day_row = rows[week_start + timedelta(days=1)]
        night_row = rows[week_start + timedelta(days=2)]

        def on_shift(now: datetime) -> bool:
            return (
                scheduling_service.shift_windows(
                    session,
                    business_unit_id=bu,
                    agent_ids=["sched-boundary-agent"],
                    now=now,
                ).get("sched-boundary-agent")
                is not None
            )

        day_start = _as_utc(day_row.start_at)
        day_end = _as_utc(day_row.end_at)
        assert on_shift(day_start) is True
        assert on_shift(day_start + timedelta(minutes=1)) is True
        assert on_shift(day_end - timedelta(minutes=1)) is True
        assert on_shift(day_end) is False

        night_start = _as_utc(night_row.start_at)
        night_end = _as_utc(night_row.end_at)
        assert night_end.date() == (
            night_row.shift_date + timedelta(days=1)
        )
        assert on_shift(night_start) is True
        # 03:00 on the next local day is still inside the cross-day shift.
        assert on_shift(night_start + timedelta(hours=5)) is True
        assert on_shift(night_end) is False


def test_auto_assign_respects_published_schedule(
    client: TestClient,
    bu: str,
) -> None:
    week_start = _current_week_start()
    _heartbeat(client, "sched-shift-agent", bu)
    _heartbeat(client, "sched-off-agent", bu)
    shift = _create_shift(client, bu, name="排班派单班")
    draft = _create_draft(client, bu, week_start)
    assert _save(
        client,
        bu,
        draft,
        _week_entries(week_start, str(shift["id"]), ["sched-shift-agent"]),
    ).status_code == 200
    assert _publish(client, bu, draft).status_code == 200
    assert _enable_policy(client, bu).status_code == 200

    conversation_id = _seed_waiting_conversation(bu)

    assigned = client.post(
        "/api/v1/customer-service/assignment-queue/auto-assign",
        headers=_admin(bu),
    )
    assert assigned.status_code == 200, assigned.text
    detail = {
        item["conversation_id"]: item
        for item in assigned.json()["assignments"]
    }.get(conversation_id)
    assert detail is not None, assigned.json()
    assert detail["agent_id"] == "sched-shift-agent"
    assert "当班" in detail["reason"]
    candidates = {item["agent_id"]: item for item in detail["candidates"]}
    assert candidates["sched-shift-agent"]["schedule_enforced"] is True
    assert candidates["sched-shift-agent"]["on_shift"] is True
    assert candidates["sched-off-agent"]["eligible"] is False
    assert "未在已发布班表当班" in candidates["sched-off-agent"][
        "excluded_reasons"
    ]

    assert _enable_policy(client, bu, False).status_code == 200
    _seed_waiting_conversation(bu)
    unrestricted = client.post(
        "/api/v1/customer-service/assignment-queue/auto-assign",
        headers=_admin(bu),
    )
    assert unrestricted.status_code == 200
    assert all(
        item["agent_id"] in {"sched-shift-agent", "sched-off-agent"}
        for item in unrestricted.json()["assignments"]
    )

    # Turning the switch off must not unbind the conversation that was already
    # assigned while the agent was on shift.
    with system_session() as session:
        conversation = session.get(
            CustomerConversation, UUID(conversation_id)
        )
        assert conversation is not None
        assert conversation.assigned_agent_id == "sched-shift-agent"


def test_manual_reassignment_is_not_schedule_gated(
    client: TestClient,
    bu: str,
) -> None:
    week_start = _current_week_start()
    _heartbeat(client, "sched-shift-agent", bu)
    _heartbeat(client, "sched-off-agent", bu)
    shift = _create_shift(client, bu, name="排班手工班")
    draft = _create_draft(client, bu, week_start)
    assert _save(
        client,
        bu,
        draft,
        _week_entries(week_start, str(shift["id"]), ["sched-shift-agent"]),
    ).status_code == 200
    assert _publish(client, bu, draft).status_code == 200
    assert _enable_policy(client, bu).status_code == 200

    conversation_id = _seed_waiting_conversation(bu)
    manual = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/reassign",
        headers=_admin(bu),
        json={
            "expected_version": 1,
            "agent_id": "sched-off-agent",
            "reason": "SUPERVISOR_REASSIGN",
        },
    )
    assert manual.status_code == 200, manual.text
    assert manual.json()["assigned_agent_id"] == "sched-off-agent"


def test_scheduling_endpoints_require_service_admin(
    client: TestClient,
    bu: str,
) -> None:
    paths = [
        ("get", "/api/v1/scheduling/shifts"),
        ("get", "/api/v1/scheduling/rosters"),
        ("get", "/api/v1/scheduling/policy"),
        ("get", "/api/v1/scheduling/on-duty"),
    ]
    for method, path in paths:
        response = client.request(
            method,
            path,
            headers=_agent_headers("plain-agent", bu),
        )
        assert response.status_code == 403, (path, response.text)

    denied = client.post(
        "/api/v1/scheduling/shifts",
        headers=_agent_headers("plain-agent", bu),
        json={"name": "越权班次", "start_local": "09:00", "end_local": "18:00"},
    )
    assert denied.status_code == 403


def test_scheduling_is_tenant_scoped(client: TestClient, bu: str) -> None:
    other_bu = f"{bu}_other"
    _heartbeat(client, "sched-tenant-a", bu)
    shift = _create_shift(client, bu, name="排班租户班")
    draft = _create_draft(client, bu, _current_week_start())

    other_shifts = client.get(
        "/api/v1/scheduling/shifts",
        headers=_admin(other_bu),
    )
    assert other_shifts.status_code == 200
    assert other_shifts.json()["items"] == []

    cross_read = client.get(
        f"/api/v1/scheduling/rosters/{draft['id']}",
        headers=_admin(other_bu),
    )
    assert cross_read.status_code == 404
    assert cross_read.json()["code"] == "ROSTER_NOT_FOUND"

    cross_update = client.patch(
        f"/api/v1/scheduling/shifts/{shift['id']}",
        headers=_admin(other_bu),
        json={"name": "跨租户改名", "version": shift["version"]},
    )
    assert cross_update.status_code == 404
    assert cross_update.json()["code"] == "SHIFT_NOT_FOUND"


def test_scheduling_audit_events_are_recorded(
    client: TestClient,
    bu: str,
) -> None:
    week_start = _current_week_start()
    _heartbeat(client, "sched-audit-agent", bu)
    shift = _create_shift(client, bu, name="排班审计班")
    draft = _create_draft(client, bu, week_start)
    assert _save(
        client,
        bu,
        draft,
        _week_entries(week_start, str(shift["id"]), ["sched-audit-agent"]),
    ).status_code == 200
    assert _publish(client, bu, draft).status_code == 200

    with system_session() as session:
        events = set(
            session.scalars(
                select(AuditEvent.event_type).where(
                    AuditEvent.event_type.like("scheduling.%")
                )
            ).all()
        )
    assert {
        "scheduling.shift.created",
        "scheduling.roster.created",
        "scheduling.roster.draft_saved",
        "scheduling.roster.published",
    } <= events


def test_policy_rows_are_scoped_to_business_unit(
    client: TestClient,
    bu: str,
) -> None:
    _heartbeat(client, "sched-policy-a", bu)
    with system_session() as session:
        presence = session.scalar(
            select(AgentPresence).where(AgentPresence.agent_id == "sched-policy-a")
        )
        assert presence is not None
        assert presence.business_unit_id == bu

        policy = session.scalar(
            select(AgentSchedulingPolicy).where(
                AgentSchedulingPolicy.business_unit_id == f"{bu}_other"
            )
        )
        assert policy is None

        shift = session.scalar(
            select(AgentShiftTemplate).where(
                AgentShiftTemplate.business_unit_id == f"{bu}_other"
            )
        )
        assert shift is None


def test_dst_nonexistent_and_ambiguous_shift_times_are_rejected(
    client: TestClient,
    bu: str,
) -> None:
    _heartbeat(client, "sched-dst-agent", bu)
    spring_shift = _create_shift(
        client, bu, name="DST跳变班", start_local="02:00", end_local="03:00"
    )
    spring_week = date(2026, 3, 2)
    spring_draft = _create_draft(
        client, bu, spring_week, timezone="America/New_York"
    )
    spring_save = _save(
        client,
        bu,
        spring_draft,
        [
            {
                "agent_id": "sched-dst-agent",
                "shift_template_id": str(spring_shift["id"]),
                "shift_date": "2026-03-08",
            }
        ],
    )
    assert spring_save.status_code == 422, spring_save.text
    assert spring_save.json()["code"] == "INVALID_SHIFT_TIME"
    spring_detail = client.get(
        f"/api/v1/scheduling/rosters/{spring_draft['id']}", headers=_admin(bu)
    )
    assert spring_detail.json()["entries"] == []

    fall_shift = _create_shift(
        client, bu, name="DST回拨班", start_local="01:30", end_local="02:30"
    )
    fall_week = date(2026, 10, 26)
    fall_draft = _create_draft(client, bu, fall_week, timezone="America/New_York")
    fall_save = _save(
        client,
        bu,
        fall_draft,
        [
            {
                "agent_id": "sched-dst-agent",
                "shift_template_id": str(fall_shift["id"]),
                "shift_date": "2026-11-01",
            }
        ],
    )
    assert fall_save.status_code == 422, fall_save.text
    assert fall_save.json()["code"] == "INVALID_SHIFT_TIME"
    fall_detail = client.get(
        f"/api/v1/scheduling/rosters/{fall_draft['id']}", headers=_admin(bu)
    )
    assert fall_detail.json()["entries"] == []


def test_enforced_policy_does_not_fall_back_without_current_week_roster(
    client: TestClient,
    bu: str,
) -> None:
    week_start = _current_week_start()
    _heartbeat(client, "sched-gap-agent", bu)
    shift = _create_shift(client, bu, name="排班缺口班")
    draft = _create_draft(client, bu, week_start)
    assert _save(
        client,
        bu,
        draft,
        _week_entries(week_start, str(shift["id"]), ["sched-gap-agent"]),
    ).status_code == 200
    assert _publish(client, bu, draft).status_code == 200
    enabled = _enable_policy(client, bu)
    assert enabled.status_code == 200, enabled.text

    # Simulate a later week where the current week has no PUBLISHED roster:
    # the policy stays enabled and must not silently fall back to old rules.
    with system_session() as session:
        roster = session.get(AgentRoster, UUID(str(draft["id"])))
        assert roster is not None
        roster.status = "ARCHIVED"
        session.commit()

    conversation_id = _seed_waiting_conversation(bu)
    assigned = client.post(
        "/api/v1/customer-service/assignment-queue/auto-assign",
        headers=_admin(bu),
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["assignments"] == []

    with system_session() as session:
        conversation = session.get(CustomerConversation, UUID(conversation_id))
        assert conversation is not None
        assert conversation.assigned_agent_id is None

    on_duty = client.get("/api/v1/scheduling/on-duty", headers=_admin(bu))
    assert on_duty.status_code == 200
    payload = on_duty.json()
    assert payload["schedule_enforced"] is True
    assert payload["schedule_ready"] is False
    assert payload["coverage_gap"] is True
    by_agent = {item["agent_id"]: item for item in payload["items"]}
    assert by_agent["sched-gap-agent"]["on_shift"] is False
    assert "未在已发布班表当班" in by_agent["sched-gap-agent"]["excluded_reasons"]

    policy = client.get("/api/v1/scheduling/policy", headers=_admin(bu))
    assert policy.status_code == 200
    assert policy.json()["enforce_published_schedule"] is True
    assert policy.json()["schedule_ready"] is False
    assert policy.json()["coverage_gap"] is True


def test_schedule_policy_is_evaluated_per_business_unit(
    client: TestClient,
    bu: str,
) -> None:
    week_start = _current_week_start()
    other_bu = f"{bu}_peer"
    _heartbeat(client, "sched-unit-a-agent", bu)
    _heartbeat(client, "sched-unit-b-agent", other_bu)
    shift = _create_shift(client, bu, name="分单元班")
    draft = _create_draft(client, bu, week_start)
    assert _save(
        client,
        bu,
        draft,
        _week_entries(week_start, str(shift["id"]), ["sched-unit-a-agent"]),
    ).status_code == 200
    assert _publish(client, bu, draft).status_code == 200
    assert _enable_policy(client, bu).status_code == 200

    enforced_conversation = _seed_waiting_conversation(bu)
    open_conversation = _seed_waiting_conversation(other_bu)

    enforced = client.post(
        "/api/v1/customer-service/assignment-queue/auto-assign",
        headers=_admin(bu),
    )
    assert enforced.status_code == 200, enforced.text
    enforced_detail = {
        item["conversation_id"]: item
        for item in enforced.json()["assignments"]
    }[enforced_conversation]
    assert enforced_detail["agent_id"] == "sched-unit-a-agent"
    assert enforced_detail["candidates"][0]["schedule_enforced"] is True

    unaffected = client.post(
        "/api/v1/customer-service/assignment-queue/auto-assign",
        headers=_admin(other_bu),
    )
    assert unaffected.status_code == 200, unaffected.text
    open_detail = {
        item["conversation_id"]: item
        for item in unaffected.json()["assignments"]
    }[open_conversation]
    assert open_detail["agent_id"] == "sched-unit-b-agent"
    candidate = {
        item["agent_id"]: item for item in open_detail["candidates"]
    }["sched-unit-b-agent"]
    assert candidate["schedule_enforced"] is False
    assert candidate["on_shift"] is False
    assert "未在已发布班表当班" not in candidate["excluded_reasons"]

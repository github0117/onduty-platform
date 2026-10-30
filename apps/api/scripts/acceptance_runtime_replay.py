#!/usr/bin/env python3
"""Live-stack acceptance for runtime replay and operations (v2 M4).

Talks to a running API over HTTP (real PostgreSQL, real worker). Two
scenarios need a precondition the public API cannot produce on demand:
retrying a ``FAILED_RETRYABLE`` turn and cancelling a queued turn. Those
preconditions are written straight into the real database with psycopg; the
behaviour under test is then exercised only through HTTP, exactly as an
operator would.

Usage:
    uv run python scripts/acceptance_runtime_replay.py [base_url]

``ACCEPTANCE_DATABASE_URL`` overrides the default
``postgresql://ticket_agent:ticket_agent@127.0.0.1:5432/ticket_agent``.

Covers:
  * the conversation turn list and replay detail (context, Skill, gate)
  * forward event pagination with after_sequence/limit/total/has_more
  * the handoff list after a supervisor employee switch
  * retrying a FAILED_RETRYABLE turn (202) and the worker picking it up
  * refusing retries of terminal / in-progress / unknown turns and roles
  * the operations turn list, runtime health and their tenant/role guards
  * RT-30: takeover cancels a queued turn and no answer is written
  * RT-07: the ticket body is only the current question
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import psycopg
from acceptance_skill_contract import (
    TERMINAL,
    _activate,
    _check,
    _create_employee,
    _events,
    _headers,
    _seed_aftersales_knowledge,
    _send,
    _start_conversation,
    _wait_turn,
)

DATABASE_URL = os.getenv(
    "ACCEPTANCE_DATABASE_URL",
    "postgresql://ticket_agent:ticket_agent@127.0.0.1:5432/ticket_agent",
)


def _mark_retryable(turn_id: str) -> None:
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(
            """
            UPDATE conversation_turns
               SET status = 'FAILED_RETRYABLE',
                   error_code = 'TURN_PROCESSING_FAILED',
                   error_message = 'acceptance: simulated transient failure',
                   attempt_count = GREATEST(attempt_count, 1),
                   completed_at = NULL,
                   updated_at = now()
             WHERE id = %s
            """,
            (str(UUID(turn_id)),),
        )


def _seed_queued_turn(
    conversation_id: str,
    *,
    employee_id: str,
    content: str,
) -> str:
    """Insert a queued turn the way the API leaves one before dispatch."""
    message_id = uuid4()
    turn_id = uuid4()
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO customer_messages
                (id, conversation_id, sequence, role, content, created_by,
                 created_at)
            VALUES (%s, %s, 1, 'BUYER', %s, 'acceptance-agent', now())
            """,
            (str(message_id), str(UUID(conversation_id)), content),
        )
        connection.execute(
            """
            INSERT INTO conversation_turns
                (id, conversation_id, sequence, status, correlation_id,
                 client_message_id, version, attempt_count, lease_expires_at,
                 stage_label, user_message_id, employee_id, analysis_json,
                 citations_json, trace_json, tool_calls_json, created_at,
                 updated_at)
            VALUES (%s, %s, 1, 'PENDING', %s, %s, 1, 0,
                    now() + interval '10 minutes', '已收到问题', %s, %s,
                    '{}'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                    now(), now())
            """,
            (
                str(turn_id),
                str(UUID(conversation_id)),
                f"acceptance-{turn_id}",
                f"acceptance-client-{turn_id}",
                str(message_id),
                str(UUID(employee_id)),
            ),
        )
    return str(turn_id)


def _messages(
    client: httpx.Client,
    conversation_id: str,
    *,
    headers: dict[str, str],
) -> list[dict[str, Any]]:
    response = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}",
        headers=headers,
    )
    response.raise_for_status()
    return cast(list[dict[str, Any]], response.json()["messages"])


def _event_page(
    client: httpx.Client,
    conversation_id: str,
    turn_id: str,
    *,
    headers: dict[str, str],
    after_sequence: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if after_sequence is not None:
        params["after_sequence"] = after_sequence
    if limit is not None:
        params["limit"] = limit
    response = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}"
        f"/turns/{turn_id}/events",
        headers=headers,
        params=params,
    )
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    suffix = uuid4().hex[:8]
    unit = "bu_demo"
    admin = _headers(f"runtime-admin-{suffix}", "admin", unit)
    supervisor = _headers(f"runtime-supervisor-{suffix}", "supervisor", unit)
    agent = _headers(f"runtime-agent-{suffix}", "agent", unit)
    checks: list[str] = []
    report: dict[str, Any] = {"suffix": suffix}

    with httpx.Client(base_url=base_url, timeout=180) as client:
        client.get("/health/ready").raise_for_status()

        employee_id = _create_employee(
            client, admin, f"runtime_replay_{suffix}", f"回放客服{suffix}"
        )
        _seed_aftersales_knowledge(client, admin, employee_id, suffix)
        _activate(client, admin, employee_id)
        agent = {**agent, "X-Business-Units": unit}

        # 1. Two turns: a small-talk fast path and an orchestrator turn.
        conversation_id = _start_conversation(
            client, agent, employee_id, f"runtime-buyer-{suffix}"
        )
        small_talk_turn, _ = _send(client, agent, conversation_id, "你好")
        _wait_turn(
            client, conversation_id, headers=agent, turn_id=small_talk_turn
        )
        turn_id, _ = _send(
            client,
            agent,
            conversation_id,
            "AB-9001 的保温杯内胆是什么材质，能保温多久？",
        )
        conversation = _wait_turn(
            client, conversation_id, headers=agent, turn_id=turn_id
        )
        turn = conversation["current_turn"]
        _check(
            turn["status"] in TERMINAL,
            f"knowledge turn finished ({turn['status']})",
            checks,
        )
        report["turn"] = {
            "id": turn_id,
            "conversation_id": conversation_id,
            "status": turn["status"],
        }

        # 2. Turn list and replay detail.
        listed = client.get(
            f"/api/v1/customer-service/conversations/{conversation_id}/turns",
            headers=agent,
        )
        listed.raise_for_status()
        listed_body = listed.json()
        _check(listed_body["total"] == 2, "turn list reports both turns", checks)
        _check(
            [item["id"] for item in listed_body["items"]]
            == [turn_id, small_talk_turn],
            "turn list is newest-first",
            checks,
        )

        detail = client.get(
            f"/api/v1/customer-service/conversations/{conversation_id}"
            f"/turns/{turn_id}",
            headers=agent,
        )
        detail.raise_for_status()
        replay = detail.json()
        _check(replay["context"] is not None, "replay detail exposes context", checks)
        _check(
            replay["context"]["schema_version"] == 2,
            "replay context snapshot is v2",
            checks,
        )
        _check("skill_version" in replay, "replay detail exposes Skill version", checks)
        _check("completion" in replay, "replay detail exposes completion", checks)
        _check(
            replay["gate"] is not None,
            f"replay detail exposes gate ({replay['gate']})",
            checks,
        )

        small_talk_detail = client.get(
            f"/api/v1/customer-service/conversations/{conversation_id}"
            f"/turns/{small_talk_turn}",
            headers=agent,
        )
        small_talk_detail.raise_for_status()
        _check(
            small_talk_detail.json()["gate"]["decision"] == "AUTO_SEND",
            "small talk turn keeps its AUTO_SEND gate in replay",
            checks,
        )

        # 3. Event pagination walks the same log the full read returns.
        full_events = _events(client, conversation_id, turn_id, headers=agent)
        first_page = _event_page(
            client, conversation_id, turn_id, headers=agent, limit=2
        )
        _check(
            len(first_page["events"]) == min(2, len(full_events)),
            "event page honours limit",
            checks,
        )
        _check(
            first_page["total"] == len(full_events),
            "event page reports the full total",
            checks,
        )
        _check(
            first_page["has_more"] == (len(full_events) > 2),
            "event page reports has_more",
            checks,
        )
        walked = [event["sequence"] for event in first_page["events"]]
        cursor = walked[-1] if walked else 0
        while True:
            page = _event_page(
                client,
                conversation_id,
                turn_id,
                headers=agent,
                after_sequence=cursor,
                limit=2,
            )
            walked.extend(event["sequence"] for event in page["events"])
            if not page["has_more"]:
                break
            cursor = walked[-1]
        _check(
            walked == [event["sequence"] for event in full_events],
            "paging forward reproduces the full event sequence",
            checks,
        )

        # 4. Handoff list after a supervisor switch.
        source = _create_employee(
            client, admin, f"runtime_handoff_src_{suffix}", f"原客服{suffix}"
        )
        target = _create_employee(
            client, admin, f"runtime_handoff_dst_{suffix}", f"接手客服{suffix}"
        )
        _activate(client, admin, source)
        _activate(client, admin, target)
        handoff_conversation = _start_conversation(
            client, agent, source, f"runtime-handoff-{suffix}"
        )
        _wait_turn(
            client,
            handoff_conversation,
            headers=agent,
            turn_id=_send(client, agent, handoff_conversation, "你好")[0],
        )
        switched = client.post(
            f"/api/v1/customer-service/conversations/{handoff_conversation}"
            "/employee",
            headers=supervisor,
            json={"employee_id": target, "reason": "运行回放验收转接"},
        )
        switched.raise_for_status()
        handoffs = client.get(
            f"/api/v1/customer-service/conversations/{handoff_conversation}"
            "/handoffs",
            headers=agent,
        )
        handoffs.raise_for_status()
        handoff_items = handoffs.json()["items"]
        _check(
            len(handoff_items) == 1
            and handoff_items[0]["kind"] == "OPERATOR_SWITCH"
            and handoff_items[0]["to_employee_id"] == target,
            "handoff list shows the supervisor switch",
            checks,
        )

        # 5. Operations views and their guards.
        health = client.get(
            "/api/v1/operations/runtime-health",
            headers=supervisor,
            params={"window_hours": 24},
        )
        health.raise_for_status()
        health_body = health.json()
        _check(
            health_body["business_unit_id"] == unit
            and health_body["turn_count"] >= 2,
            "runtime health counts the window's turns",
            checks,
        )
        _check(
            health_body["auto_send_count"] >= 1
            and health_body["auto_send_rate"] is not None,
            "runtime health reports the auto-send rate",
            checks,
        )
        _check(
            isinstance(health_body["top_gaps"], list),
            "runtime health returns the top knowledge gaps",
            checks,
        )
        report["runtime_health"] = health_body

        ops_turns = client.get(
            "/api/v1/operations/turns", headers=supervisor
        )
        ops_turns.raise_for_status()
        ops_ids = {item["id"] for item in ops_turns.json()["items"]}
        _check(turn_id in ops_ids, "operations turn list contains the turn", checks)
        completed = client.get(
            "/api/v1/operations/turns",
            headers=supervisor,
            params={"status": "COMPLETED"},
        )
        completed.raise_for_status()
        _check(
            all(
                item["status"] == "COMPLETED"
                for item in completed.json()["items"]
            ),
            "operations status filter returns only that status",
            checks,
        )
        _check(
            client.get(
                "/api/v1/operations/turns", headers=agent
            ).status_code
            == 403,
            "agent cannot read the operations turn list (403)",
            checks,
        )
        _check(
            client.get(
                "/api/v1/operations/runtime-health", headers=agent
            ).status_code
            == 403,
            "agent cannot read runtime health (403)",
            checks,
        )
        _check(
            client.get(
                "/api/v1/operations/runtime-health",
                headers=supervisor,
                params={"business_unit_id": "bu_other"},
            ).status_code
            == 403,
            "runtime health rejects a foreign tenant (403)",
            checks,
        )

        # 6. Retry guards.
        terminal_retry = client.post(
            f"/api/v1/customer-service/turns/{turn_id}/retry",
            headers=supervisor,
        )
        _check(
            terminal_retry.status_code == 409
            and terminal_retry.json().get("code") == "TURN_ALREADY_TERMINAL",
            "completed turn cannot be retried (409 TURN_ALREADY_TERMINAL)",
            checks,
        )
        _check(
            client.post(
                f"/api/v1/customer-service/turns/{turn_id}/retry",
                headers=agent,
            ).status_code
            == 403,
            "agent cannot retry a turn (403)",
            checks,
        )
        _check(
            client.post(
                f"/api/v1/customer-service/turns/{uuid4()}/retry",
                headers=supervisor,
            ).status_code
            == 404,
            "unknown turn retry is a 404",
            checks,
        )
        _check(
            client.post(
                f"/api/v1/customer-service/turns/{turn_id}/retry",
                headers={**supervisor, "X-Business-Unit-Id": "bu_other"},
            ).status_code
            == 403,
            "retry from another tenant is rejected (403)",
            checks,
        )

        # 7. Retry a seeded retryable failure and watch the worker resume it.
        retry_conversation = _start_conversation(
            client, agent, employee_id, f"runtime-retry-{suffix}"
        )
        retry_turn_id, _ = _send(
            client, agent, retry_conversation, "保温杯能保温多久？"
        )
        _wait_turn(
            client,
            retry_conversation,
            headers=agent,
            turn_id=retry_turn_id,
        )
        _mark_retryable(retry_turn_id)
        retried = client.post(
            f"/api/v1/customer-service/turns/{retry_turn_id}/retry",
            headers=supervisor,
        )
        _check(
            retried.status_code == 202,
            f"retryable turn requeues (got {retried.status_code})",
            checks,
        )
        _check(
            retried.json()["status"] == "PENDING",
            "retry response puts the turn back in PENDING",
            checks,
        )
        deadline = time.monotonic() + 120
        retried_status = retried.json()["status"]
        while time.monotonic() < deadline:
            current = client.get(
                f"/api/v1/customer-service/conversations/{retry_conversation}",
                headers=agent,
            )
            current.raise_for_status()
            retried_status = (current.json().get("current_turn") or {}).get(
                "status", retried_status
            )
            if retried_status in TERMINAL:
                break
            time.sleep(0.5)
        _check(
            retried_status in TERMINAL,
            f"worker resumes the retried turn ({retried_status})",
            checks,
        )
        retry_events = _events(
            client, retry_conversation, retry_turn_id, headers=agent
        )
        retry_event = next(
            (
                event
                for event in retry_events
                if event["payload"].get("reason_code") == "OPERATOR_RETRY"
            ),
            None,
        )
        _check(
            retry_event is not None
            and retry_event["actor_type"] == "AGENT",
            "retry is recorded as an operator action",
            checks,
        )
        _check(
            any(event["event_type"] == "TURN_STARTED" for event in retry_events),
            "worker logs a TURN_STARTED after the retry",
            checks,
        )
        report["retried_turn"] = {
            "id": retry_turn_id,
            "status": retried_status,
        }

        # 8. RT-30: takeover cancels the queued turn and writes no answer.
        cancel_conversation = _start_conversation(
            client, agent, employee_id, f"runtime-cancel-{suffix}"
        )
        queued_turn = _seed_queued_turn(
            cancel_conversation,
            employee_id=employee_id,
            content="我的订单 AB-9001 一直没发货",
        )
        before = client.get(
            f"/api/v1/customer-service/conversations/{cancel_conversation}",
            headers=agent,
        )
        before.raise_for_status()
        takeover = client.post(
            f"/api/v1/customer-service/conversations/{cancel_conversation}"
            "/takeover",
            headers=agent,
            json={"expected_version": before.json()["version"]},
        )
        takeover.raise_for_status()
        cancel_events = _events(
            client, cancel_conversation, queued_turn, headers=agent
        )
        cancelled = next(
            (
                event
                for event in cancel_events
                if event["event_type"] == "TURN_CANCELLED"
            ),
            None,
        )
        _check(
            cancelled is not None
            and cancelled["payload"].get("reason_code") == "HUMAN_TAKEOVER",
            "takeover logs TURN_CANCELLED with HUMAN_TAKEOVER",
            checks,
        )
        time.sleep(3)
        roles = [
            message["role"]
            for message in _messages(
                client, cancel_conversation, headers=agent
            )
        ]
        _check(
            roles == ["BUYER"],
            f"takeover leaves no assistant answer (messages={roles})",
            checks,
        )
        _check(
            client.post(
                f"/api/v1/customer-service/turns/{queued_turn}/retry",
                headers=supervisor,
            ).status_code
            == 409,
            "a cancelled turn cannot be retried back to life (409)",
            checks,
        )
        report["cancelled_turn"] = {
            "id": queued_turn,
            "conversation_id": cancel_conversation,
        }

        # 9. RT-07: the ticket body follows the current question only.
        current_question = "那发票还能开吗？"
        third = client.post(
            f"/api/v1/customer-service/conversations/{conversation_id}/messages",
            headers=agent,
            json={"content": current_question},
        )
        third.raise_for_status()
        third_body = third.json()
        ticket_id = third_body["current_ticket_id"]
        ticket = client.get(f"/api/v1/tickets/{ticket_id}", headers=agent)
        ticket.raise_for_status()
        ticket_body = ticket.json()["body"]
        _check(
            ticket_body == current_question,
            f"ticket body is exactly the current question ({ticket_body!r})",
            checks,
        )
        _check(
            "保温杯" not in ticket_body and "你好" not in ticket_body,
            "ticket body does not replay earlier conversation",
            checks,
        )

        # 10. The greeting fast path reads what the conversation remembered.
        greeting_turn, _ = _send(client, agent, conversation_id, "你好")
        greeting_view = _wait_turn(
            client,
            conversation_id,
            headers=agent,
            turn_id=greeting_turn,
        )
        greeting_reply = greeting_view["messages"][-1]["content"]
        _check(
            "AB-9001" in greeting_reply,
            f"greeting reuses the remembered order ({greeting_reply!r})",
            checks,
        )
        greeting_detail = client.get(
            f"/api/v1/customer-service/conversations/{conversation_id}"
            f"/turns/{greeting_turn}",
            headers=agent,
        )
        greeting_detail.raise_for_status()
        greeting_replay = greeting_detail.json()
        _check(
            greeting_replay["context"] is not None
            and greeting_replay["context"]["memory"]["fact_count"] >= 1,
            "greeting records the memory snapshot it read",
            checks,
        )
        _check(
            any(
                event["event_type"] == "CONTEXT_ASSEMBLED"
                for event in _events(
                    client, conversation_id, greeting_turn, headers=agent
                )
            ),
            "greeting logs CONTEXT_ASSEMBLED",
            checks,
        )

        # 11. A human takes the conversation over and hands it back.
        human_conversation = _start_conversation(
            client, agent, employee_id, f"runtime-human-{suffix}"
        )
        complaint_turn, _ = _send(
            client,
            agent,
            human_conversation,
            "我要投诉！保温杯内胆是什么材质？必须马上答复，否则曝光。",
        )
        complaint_view = _wait_turn(
            client,
            human_conversation,
            headers=agent,
            turn_id=complaint_turn,
        )
        human_ticket_id = complaint_view["current_ticket_id"]
        _check(
            complaint_view["current_workflow_state"] != "COMPLETED",
            "the complaint leaves a ticket a human can handle "
            f"({complaint_view['current_workflow_state']})",
            checks,
        )
        assistant_before = sum(
            message["role"] == "ASSISTANT"
            for message in complaint_view["messages"]
        )
        takeover = client.post(
            f"/api/v1/customer-service/conversations/{human_conversation}"
            "/takeover",
            headers=agent,
            json={"expected_version": complaint_view["version"]},
        )
        _check(takeover.status_code == 200, "human takes over (200)", checks)
        ticket_after_takeover = client.get(
            f"/api/v1/tickets/{human_ticket_id}", headers=agent
        )
        ticket_after_takeover.raise_for_status()
        ticket_state = ticket_after_takeover.json()
        _check(
            ticket_state["workflow_state"] == "TAKEN_OVER",
            f"takeover moves the ticket to TAKEN_OVER "
            f"({ticket_state['workflow_state']})",
            checks,
        )
        handoffs = client.get(
            f"/api/v1/customer-service/conversations/{human_conversation}"
            "/handoffs",
            headers=agent,
        )
        handoffs.raise_for_status()
        takeover_handoff = handoffs.json()["items"][-1]
        _check(
            takeover_handoff["kind"] == "HUMAN_TAKEOVER"
            and takeover_handoff["to_employee_id"] is None
            and takeover_handoff["from_employee_id"] == employee_id,
            "takeover records a HUMAN_TAKEOVER handoff",
            checks,
        )

        owned = client.post(
            f"/api/v1/customer-service/conversations/{human_conversation}"
            "/messages",
            headers=agent,
            json={"content": "你好"},
        )
        _check(owned.status_code == 202, "buyer can still write (202)", checks)
        owned_body = owned.json()
        _check(
            owned_body["current_turn"]["status"] == "NEEDS_HUMAN",
            "message during human ownership is NEEDS_HUMAN "
            f"({owned_body['current_turn']['status']})",
            checks,
        )
        _check(
            sum(
                message["role"] == "ASSISTANT"
                for message in owned_body["messages"]
            )
            == assistant_before,
            "the digital employee does not answer over the human",
            checks,
        )

        replied = client.post(
            f"/api/v1/customer-service/conversations/{human_conversation}"
            "/manual-replies",
            headers=agent,
            json={"content": "我来处理你的投诉，请稍等。"},
        )
        _check(
            replied.status_code == 201,
            f"human replies while owning the conversation "
            f"(got {replied.status_code})",
            checks,
        )
        still_owned = client.post(
            f"/api/v1/customer-service/conversations/{human_conversation}"
            "/messages",
            headers=agent,
            json={"content": "谢谢"},
        )
        _check(
            still_owned.status_code == 202
            and still_owned.json()["current_turn"]["status"] == "NEEDS_HUMAN",
            "a second message stays with the human",
            checks,
        )

        resolved = client.post(
            f"/api/v1/customer-service/conversations/{human_conversation}"
            "/manual-replies",
            headers=agent,
            json={"content": "已处理完毕，后续由数字员工接待。", "resolve": True},
        )
        _check(
            resolved.status_code == 201
            and resolved.json()["assigned_agent_id"] is None,
            "human resolves and hands the conversation back",
            checks,
        )
        handoffs = client.get(
            f"/api/v1/customer-service/conversations/{human_conversation}"
            "/handoffs",
            headers=agent,
        )
        handoffs.raise_for_status()
        return_handoff = handoffs.json()["items"][-1]
        _check(
            return_handoff["kind"] == "HUMAN_RETURN"
            and return_handoff["from_employee_id"] is None
            and return_handoff["to_employee_id"] == employee_id,
            "hand-back records a HUMAN_RETURN handoff",
            checks,
        )
        _check(
            return_handoff["summary"]["last_answer"]["by"] == "human"
            and return_handoff["summary"]["last_answer"]["text"]
            == "已处理完毕，后续由数字员工接待。",
            "hand-back summary carries the human's last reply",
            checks,
        )

        back_turn, _ = _send(client, agent, human_conversation, "你好")
        back_view = _wait_turn(
            client,
            human_conversation,
            headers=agent,
            turn_id=back_turn,
        )
        _check(
            back_view["current_turn"]["status"] == "COMPLETED"
            and back_view["messages"][-1]["role"] == "ASSISTANT",
            "after the hand-back the digital employee answers again",
            checks,
        )
        report["human_handoff"] = {
            "conversation_id": human_conversation,
            "ticket_id": human_ticket_id,
            "takeover_handoff_id": takeover_handoff["id"],
            "return_handoff_id": return_handoff["id"],
        }

    report["checks"] = checks
    print(
        __import__("json").dumps(report, ensure_ascii=False, indent=2)
    )
    print(f"\n{len(checks)} checks passed")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - acceptance script reports and exits
        print(f"FAILED: {error}", file=sys.stderr)
        raise SystemExit(1) from error

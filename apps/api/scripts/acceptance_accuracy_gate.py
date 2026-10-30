#!/usr/bin/env python3
"""Live-stack acceptance for the accuracy gate (v2 M3).

Talks to a running API over HTTP only: real PostgreSQL, real worker, real
outbox. It does not import the application, so a pass means the deployed
process really behaves this way.

Usage:
    ACCEPTANCE_CONNECTOR_SECRET=... \\
        uv run python scripts/acceptance_accuracy_gate.py [base_url]

The connector secret is read from the environment; the connector references
``METRICS_SCRAPE_TOKEN`` (the demo stack's local metrics token) so no
credential is written into this file.

Covers:
  * a grounded, verified answer gets gate AUTO_SEND, a GATE_EVALUATED event
    and a COMPLETED ticket
  * a high-risk / human-bound answer gets gate HUMAN_REVIEW and is not
    auto-sent through a connector
  * small talk explicitly clears the gate (NOT_REQUIRED) and still auto-sends
  * three identical no-knowledge questions open exactly one repair task whose
    occurrence count reflects the captured gaps
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
from typing import Any, cast
from uuid import uuid4

import httpx
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

CONNECTOR_SECRET_ENV = "METRICS_SCRAPE_TOKEN"


def _create_entry(client: httpx.Client, admin: dict[str, str], suffix: str) -> str:
    response = client.post(
        "/api/v1/business-service-entries",
        headers=admin,
        json={
            "business_unit_id": "bu_demo",
            "code": f"gate_entry_{suffix}",
            "name": "门禁验收邮件入口",
            "domain": "ecommerce",
            "channel": "email",
            "human_queue_id": "MANUAL_TRIAGE",
        },
    )
    response.raise_for_status()
    return cast(str, response.json()["id"])


def _create_connector(
    client: httpx.Client,
    admin: dict[str, str],
    suffix: str,
    entry_id: str,
    employee_id: str,
) -> str:
    response = client.post(
        "/api/v1/connectors",
        headers=admin,
        json={
            "business_unit_id": "bu_demo",
            "connector_key": f"gate_mail_{suffix}",
            "name": "门禁验收邮件",
            "connector_type": "email",
            "direction": "BIDIRECTIONAL",
            "config": {
                "imap_host": "mock-mail",
                "imap_port": 3143,
                "imap_ssl": False,
                "smtp_host": "mock-mail",
                "smtp_port": 3025,
                "smtp_ssl": False,
                "from_address": "support@example.com",
                "timeout_seconds": 5,
            },
            "secret_ref": CONNECTOR_SECRET_ENV,
            "auto_reply_enabled": True,
        },
    )
    response.raise_for_status()
    connector_id = cast(str, response.json()["id"])
    bound = client.put(
        f"/api/v1/connectors/{connector_id}/bindings",
        headers=admin,
        json={
            "bindings": [
                {
                    "service_entry_id": entry_id,
                    "employee_id": employee_id,
                    "allowed_operations": ["knowledge.search"],
                }
            ]
        },
    )
    bound.raise_for_status()
    return connector_id


def _webhook(
    client: httpx.Client,
    connector_id: str,
    payload: dict[str, object],
    secret: str,
) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode()
    signature = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    response = client.post(
        f"/api/v1/connectors/{connector_id}/inbound",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Connector-Signature": signature,
        },
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"webhook rejected: {response.status_code} {response.text}"
        )


def _messages(
    client: httpx.Client,
    admin: dict[str, str],
    connector_id: str,
) -> dict[str, Any]:
    response = client.get(
        f"/api/v1/connectors/{connector_id}/messages",
        headers=admin,
    )
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


def _wait_inbound(
    client: httpx.Client,
    admin: dict[str, str],
    connector_id: str,
    external_message_id: str,
    *,
    timeout: float = 180.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        for row in _messages(client, admin, connector_id)["inbound"]:
            if row["external_message_id"] != external_message_id:
                continue
            last = cast(dict[str, Any], row)
            if row["status"] in {"PROCESSED", "FAILED"}:
                return last
        time.sleep(0.5)
    raise RuntimeError(f"inbound did not finish: {json.dumps(last, ensure_ascii=False)}")


def _conversation_turn(
    client: httpx.Client,
    headers: dict[str, str],
    conversation_id: str,
) -> dict[str, Any]:
    response = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}",
        headers=headers,
    )
    response.raise_for_status()
    return cast(dict[str, Any], response.json()["current_turn"] or {})


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    secret = os.environ.get("ACCEPTANCE_CONNECTOR_SECRET", "").strip()
    if not secret:
        raise SystemExit(
            "ACCEPTANCE_CONNECTOR_SECRET is required (value of the demo "
            f"{CONNECTOR_SECRET_ENV} in the running stack)."
        )
    suffix = uuid4().hex[:8]
    unit = "bu_demo"
    admin = _headers(f"gate-acceptance-admin-{suffix}", "admin", unit)
    agent = _headers(f"gate-acceptance-agent-{suffix}", "agent", unit)
    buyer = f"gate-buyer-{suffix}@example.com"
    checks: list[str] = []
    report: dict[str, Any] = {"suffix": suffix}

    with httpx.Client(base_url=base_url, timeout=180) as client:
        client.get("/health/ready").raise_for_status()

        # 1. Grounded, verified answer -> AUTO_SEND, event, completed ticket.
        employee_id = _create_employee(
            client, admin, f"gate_employee_{suffix}", "门禁验收客服"
        )
        _seed_aftersales_knowledge(client, admin, employee_id, suffix)
        _activate(client, admin, employee_id)
        conversation_id = _start_conversation(
            client, agent, employee_id, f"gate-grounded-{suffix}"
        )
        turn_id, _ = _send(client, agent, conversation_id, "保温杯内胆是什么材质？")
        body = _wait_turn(
            client,
            conversation_id,
            headers=agent,
            turn_id=turn_id,
        )
        turn = body["current_turn"]
        _check(
            turn["status"] == "COMPLETED",
            "grounded answer turn completes",
            checks,
        )
        gate = turn.get("gate") or {}
        _check(
            gate.get("decision") == "AUTO_SEND",
            f"grounded answer is AUTO_SEND (got {gate.get('decision')})",
            checks,
        )
        _check(gate.get("reasons") == [], "AUTO_SEND carries no reasons", checks)
        _check(
            gate.get("checks", {}).get("claim_count", 0) >= 1,
            "gate recorded the claims it checked",
            checks,
        )
        events = _events(client, conversation_id, turn_id, headers=agent)
        gate_event = next(
            (
                event
                for event in events
                if event["event_type"] == "GATE_EVALUATED"
            ),
            None,
        )
        _check(gate_event is not None, "turn recorded GATE_EVALUATED", checks)
        _check(
            gate_event is not None
            and gate_event["payload"].get("decision") == "AUTO_SEND",
            "GATE_EVALUATED payload carries AUTO_SEND",
            checks,
        )
        ticket = client.get(
            f"/api/v1/tickets/{turn['ticket_id']}",
            headers=agent,
        )
        ticket.raise_for_status()
        _check(
            ticket.json()["workflow_state"] == "COMPLETED",
            "AUTO_SEND grounded turn completes the ticket",
            checks,
        )
        report["grounded_gate"] = gate

        # 2. No knowledge, three identical questions -> one repair task.
        gap_employee = _create_employee(
            client, admin, f"gate_gap_{suffix}", "缺口验收客服"
        )
        _activate(client, admin, gap_employee)
        gap_question = f"量子咖啡机保修几年？{suffix}"
        for index in range(3):
            gap_conversation = _start_conversation(
                client, agent, gap_employee, f"gate-gap-{suffix}-{index}"
            )
            gap_turn_id, _ = _send(
                client, agent, gap_conversation, gap_question
            )
            gap_body = _wait_turn(
                client,
                gap_conversation,
                headers=agent,
                turn_id=gap_turn_id,
            )
            gap_turn = gap_body["current_turn"]
            _check(
                gap_turn["status"] in TERMINAL,
                f"no-knowledge turn {index + 1} reaches a terminal state",
                checks,
            )
            _check(
                gap_turn.get("error_code") == "KNOWLEDGE_NOT_FOUND",
                f"no-knowledge turn {index + 1} reports KNOWLEDGE_NOT_FOUND",
                checks,
            )
        tasks = client.get(
            "/api/v1/knowledge/repair-tasks",
            params={"business_unit_id": unit},
            headers=admin,
        )
        tasks.raise_for_status()
        matching = [
            item
            for item in tasks.json()["items"]
            if item["query"] == gap_question
        ]
        _check(
            len(matching) == 1,
            f"three repeated gaps open exactly one repair task (got {len(matching)})",
            checks,
        )
        _check(
            len(matching) == 1 and matching[0]["occurrence_count"] >= 3,
            "repair task reports at least three occurrences",
            checks,
        )
        report["gap_task"] = matching[0] if matching else None

        # 3. Connector: small talk clears the gate and auto-sends.
        entry_id = _create_entry(client, admin, suffix)
        connector_id = _create_connector(
            client, admin, suffix, entry_id, employee_id
        )
        small_talk_id = f"<gate-smalltalk-{suffix}@example.com>"
        _webhook(
            client,
            connector_id,
            {
                "message_id": small_talk_id,
                "thread_id": f"<gate-thread-{suffix}@example.com>",
                "user_id": buyer,
                "subject": "问候",
                "content": "你好",
                "metadata": {"mailbox": "support"},
            },
            secret,
        )
        inbound = _wait_inbound(
            client, admin, connector_id, small_talk_id
        )
        _check(
            inbound["status"] == "PROCESSED",
            "small-talk inbound is processed",
            checks,
        )
        small_talk_turn = _conversation_turn(
            client, agent, str(inbound["conversation_id"])
        )
        small_talk_gate = small_talk_turn.get("gate") or {}
        _check(
            small_talk_gate.get("decision") == "AUTO_SEND"
            and small_talk_gate.get("grounding_status") == "NOT_REQUIRED",
            "small talk records an explicit NOT_REQUIRED AUTO_SEND gate",
            checks,
        )
        outbound_after_small_talk = _messages(
            client, admin, connector_id
        )["outbound"]
        _check(
            len(outbound_after_small_talk) == 1,
            "small talk is auto-replied through the connector",
            checks,
        )
        _check(
            outbound_after_small_talk[0]["status"] == "QUEUED",
            "auto reply is queued as an outbound message",
            checks,
        )

        # 4. Connector: a human-bound answer is held, never sent.
        held_id = f"<gate-held-{suffix}@example.com>"
        _webhook(
            client,
            connector_id,
            {
                "message_id": held_id,
                "thread_id": f"<gate-held-thread-{suffix}@example.com>",
                "user_id": buyer,
                "subject": "投诉并咨询材质",
                "content": "我要投诉！保温杯内胆是什么材质？必须马上答复，否则曝光。",
                "metadata": {"mailbox": "support"},
            },
            secret,
        )
        held_inbound = _wait_inbound(client, admin, connector_id, held_id)
        _check(
            held_inbound["status"] == "PROCESSED",
            "human-bound inbound is processed",
            checks,
        )
        held_turn = _conversation_turn(
            client, agent, str(held_inbound["conversation_id"])
        )
        held_gate = held_turn.get("gate") or {}
        _check(
            held_gate.get("decision") == "HUMAN_REVIEW",
            f"human-bound answer is held (got {held_gate.get('decision')})",
            checks,
        )
        _check(
            bool(held_gate.get("reasons")),
            "HUMAN_REVIEW explains why it was held",
            checks,
        )
        outbound_final = _messages(client, admin, connector_id)["outbound"]
        _check(
            len(outbound_final) == 1,
            "held answer creates no second outbound message",
            checks,
        )
        report["held_gate"] = held_gate
        report["held_turn_status"] = held_turn.get("status")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"accuracy gate acceptance passed: {len(checks)} checks")
    for check in checks:
        print(f"  - {check}")


if __name__ == "__main__":
    main()

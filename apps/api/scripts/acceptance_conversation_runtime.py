#!/usr/bin/env python3
"""Closed-loop acceptance for the conversation runtime (v2 M1) on a live stack.

Talks to a running API over HTTP only: real PostgreSQL, real worker, real model
or its local fallback. It does not import the application, so a pass here means
the deployed process really behaves this way.

Usage:
    uv run python scripts/acceptance_conversation_runtime.py [base_url]

Covers:
  * a normal question turn and its context snapshot
  * replaying the same ``client_message_id`` returns the original turn
  * a follow-up turn keeps the conversation history
  * two messages submitted back to back run one after the other
  * queued turns never see a message sent after them
  * two first messages at the same instant share one ticket
  * operator switch: response, banner data, permission/state rejections
  * the turn after a switch assembles the handoff summary
  * a switch to another business unit's employee is refused
  * pre-M1 conversations still render
"""

import json
import sys
import threading
import time
from typing import Any, cast
from uuid import uuid4

import httpx

TERMINAL = {"COMPLETED", "NEEDS_HUMAN", "FAILED_TERMINAL", "CANCELLED"}


def _headers(actor: str, role: str, unit: str) -> dict[str, str]:
    return {
        "X-Actor-Id": actor,
        "X-Actor-Role": role,
        "X-Business-Unit-Id": unit,
    }


def _wait_latest_turn(
    client: httpx.Client,
    conversation_id: str,
    *,
    headers: dict[str, str],
    turn_id: str | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Poll until the conversation's latest turn is terminal.

    Turns run one at a time, so waiting for the latest turn also means every
    earlier turn has finished. When ``turn_id`` is given the latest turn must
    be that one (used when nothing else was queued behind it).
    """
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(
            f"/api/v1/customer-service/conversations/{conversation_id}",
            headers=headers,
        )
        response.raise_for_status()
        body = cast(dict[str, Any], response.json())
        current = body.get("current_turn") or {}
        last = current
        if turn_id is not None and current.get("id") != turn_id:
            time.sleep(0.5)
            continue
        if current.get("status") in TERMINAL:
            return body
        time.sleep(0.5)
    raise RuntimeError(f"turn did not finish: {json.dumps(last, ensure_ascii=False)}")


def _turn_status_from_events(events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        status = event["status"]
        if event["event_type"].startswith("TURN_") and status in TERMINAL:
            return cast(str, status)
    return None


def _events(
    client: httpx.Client,
    conversation_id: str,
    turn_id: str,
    *,
    headers: dict[str, str],
) -> list[dict[str, Any]]:
    response = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}/turns/{turn_id}/events",
        headers=headers,
    )
    response.raise_for_status()
    return cast(list[dict[str, Any]], response.json()["events"])


def _event(events: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    for event in events:
        if event["event_type"] == event_type:
            return event
    return None


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    suffix = uuid4().hex[:8]
    unit = "bu_demo"
    admin = _headers(f"runtime-acceptance-admin-{suffix}", "admin", unit)
    agent = _headers(f"runtime-acceptance-agent-{suffix}", "agent", unit)
    requester = _headers(f"runtime-acceptance-buyer-{suffix}", "requester", unit)
    report: dict[str, Any] = {"suffix": suffix}

    with httpx.Client(base_url=base_url, timeout=180) as client:
        client.get("/health/ready").raise_for_status()

        employees_response = client.get(
            "/api/v1/digital-employees",
            params={"business_unit_id": unit},
            headers=admin,
        )
        employees_response.raise_for_status()
        active = [
            employee
            for employee in employees_response.json()
            if employee["status"] == "ACTIVE" and employee["domain"] == "customer_service"
        ]
        if len(active) < 2:
            raise RuntimeError(f"need two active customer service employees, got {len(active)}")
        first = active[0]
        second = active[1]
        report["employees"] = {"from": first["name"], "to": second["name"]}

        conversation_response = client.post(
            "/api/v1/customer-service/conversations",
            headers=admin,
            json={
                "business_unit_id": unit,
                "employee_id": first["id"],
                "requester_ref": f"runtime-acceptance-{suffix}",
                "channel": "web_form",
            },
        )
        conversation_response.raise_for_status()
        conversation_id = conversation_response.json()["id"]
        report["conversation_id"] = conversation_id

        # 1. normal turn with a client id
        client_message_id = f"{suffix}-m1"
        message_response = client.post(
            f"/api/v1/customer-service/conversations/{conversation_id}/messages",
            headers=admin,
            json={
                "content": "这个保温杯的内胆是什么材质，能保温多久？",
                "client_message_id": client_message_id,
            },
        )
        message_response.raise_for_status()
        first_body = message_response.json()
        first_turn_id = first_body["current_turn"]["id"]
        report["first_turn"] = {
            "id": first_turn_id,
            "replayed": first_body["replayed"],
        }
        conversation = _wait_latest_turn(
            client,
            conversation_id,
            headers=admin,
            turn_id=first_turn_id,
        )
        first_turn = conversation["current_turn"]
        report["first_turn"]["status"] = first_turn["status"]
        report["first_turn"]["message_count"] = len(conversation["messages"])

        events = _events(client, conversation_id, first_turn_id, headers=admin)
        assembled = _event(events, "CONTEXT_ASSEMBLED")
        created = _event(events, "TURN_CREATED")
        started = _event(events, "TURN_STARTED")
        completed = _event(events, "TURN_COMPLETED")
        report["first_turn"]["events"] = [event["event_type"] for event in events]
        if not (created and started and assembled):
            raise RuntimeError(f"missing lifecycle events: {report['first_turn']['events']}")
        payload = assembled["payload"]
        required_context = {
            "budget_chars",
            "history_message_count",
            "history_sequences",
            "memory",
            "handoff",
        }
        missing = required_context - set(payload)
        if missing:
            raise RuntimeError(f"context snapshot missing keys: {sorted(missing)}")
        report["first_turn"]["context"] = {
            "history_message_count": payload["history_message_count"],
            "memory_schema_version": (payload["memory"] or {}).get("schema_version"),
            "handoff": payload["handoff"],
            "truncated": payload["truncated"],
            "employee_config_revision": payload.get("employee_config_revision"),
        }
        if payload["history_message_count"] != 0:
            # The first turn of a conversation has no earlier messages to
            # replay; the current message is carried separately.
            raise RuntimeError(
                f"first turn should have no history, saw {payload['history_message_count']}"
            )
        if not completed and first_turn["status"] == "COMPLETED":
            raise RuntimeError("COMPLETED turn without TURN_COMPLETED event")

        # 2. replay: same client_message_id must not create a second turn
        replay_response = client.post(
            f"/api/v1/customer-service/conversations/{conversation_id}/messages",
            headers=admin,
            json={
                "content": "这个保温杯的内胆是什么材质，能保温多久？",
                "client_message_id": client_message_id,
            },
        )
        replay_response.raise_for_status()
        replay = replay_response.json()
        report["replay"] = {
            "replayed": replay["replayed"],
            "same_turn": replay["current_turn"]["id"] == first_turn_id,
            "message_count": len(replay["messages"]),
        }
        if not replay["replayed"] or replay["current_turn"]["id"] != first_turn_id:
            raise RuntimeError(f"replay was not detected: {report['replay']}")
        if len(replay["messages"]) != len(conversation["messages"]):
            raise RuntimeError("replay wrote extra messages")

        # 3. two follow-ups submitted back to back: serialised, both recorded once
        second_id = f"{suffix}-m2"
        third_id = f"{suffix}-m3"
        second_response = client.post(
            f"/api/v1/customer-service/conversations/{conversation_id}/messages",
            headers=admin,
            json={"content": "那清洗的时候要注意什么？", "client_message_id": second_id},
        )
        second_response.raise_for_status()
        second_turn_id = second_response.json()["current_turn"]["id"]
        third_response = client.post(
            f"/api/v1/customer-service/conversations/{conversation_id}/messages",
            headers=admin,
            json={"content": "杯子有保修吗？", "client_message_id": third_id},
        )
        third_response.raise_for_status()
        third_turn_id = third_response.json()["current_turn"]["id"]
        if second_turn_id == third_turn_id:
            raise RuntimeError("back-to-back messages collapsed into one turn")
        conversation = _wait_latest_turn(
            client,
            conversation_id,
            headers=admin,
            turn_id=third_turn_id,
        )
        second_events = _events(client, conversation_id, second_turn_id, headers=admin)
        third_events = _events(client, conversation_id, third_turn_id, headers=admin)
        second_status = _turn_status_from_events(second_events)
        third_status = _turn_status_from_events(third_events)
        if second_status is None or third_status is None:
            raise RuntimeError("queued turns did not both reach a terminal status")
        report["serialisation"] = {
            "second_status": second_status,
            "third_status": third_status,
            "message_count": len(conversation["messages"]),
        }
        third_events = _events(client, conversation_id, third_turn_id, headers=admin)
        third_assembled = _event(third_events, "CONTEXT_ASSEMBLED")
        if third_assembled is None:
            raise RuntimeError("third turn has no context snapshot")
        if third_assembled["payload"]["history_message_count"] < 3:
            raise RuntimeError(
                "third turn should see earlier messages, saw "
                f"{third_assembled['payload']['history_message_count']}"
            )
        report["serialisation"]["third_history_count"] = third_assembled["payload"][
            "history_message_count"
        ]

        # 4. operator switch: rejections first
        current = client.get(
            f"/api/v1/customer-service/conversations/{conversation_id}",
            headers=admin,
        ).json()
        current_employee_id = current["employee_id"]
        target = next(employee for employee in active if employee["id"] != current_employee_id)
        agent_attempt = client.post(
            f"/api/v1/customer-service/conversations/{conversation_id}/employee",
            headers=agent,
            json={"employee_id": target["id"], "reason": "acceptance"},
        )
        requester_attempt = client.post(
            f"/api/v1/customer-service/conversations/{conversation_id}/employee",
            headers=requester,
            json={"employee_id": target["id"], "reason": "acceptance"},
        )
        unchanged_attempt = client.post(
            f"/api/v1/customer-service/conversations/{conversation_id}/employee",
            headers=admin,
            json={"employee_id": current_employee_id, "reason": "acceptance"},
        )
        unknown_attempt = client.post(
            f"/api/v1/customer-service/conversations/{conversation_id}/employee",
            headers=admin,
            json={"employee_id": str(uuid4()), "reason": "acceptance"},
        )
        report["switch_rejections"] = {
            "agent": agent_attempt.status_code,
            "requester": requester_attempt.status_code,
            "same_employee": unchanged_attempt.status_code,
            "same_employee_code": _problem_code(unchanged_attempt),
            "unknown_employee": unknown_attempt.status_code,
            "unknown_employee_code": _problem_code(unknown_attempt),
        }
        if agent_attempt.status_code != 403 or requester_attempt.status_code != 403:
            raise RuntimeError(f"switch allowed for a non-operator: {report['switch_rejections']}")
        if unchanged_attempt.status_code != 409:
            raise RuntimeError(f"same-employee switch not rejected: {report['switch_rejections']}")
        if unknown_attempt.status_code != 404:
            raise RuntimeError(f"unknown employee not rejected: {report['switch_rejections']}")

        switch_response = client.post(
            f"/api/v1/customer-service/conversations/{conversation_id}/employee",
            headers=admin,
            json={"employee_id": target["id"], "reason": "验收：换专家继续跟进"},
        )
        switch_response.raise_for_status()
        switched = switch_response.json()
        handoff = switched["latest_handoff"]
        if handoff is None or handoff["to_employee_id"] != target["id"]:
            raise RuntimeError(f"switch did not record a handoff: {switched.get('latest_handoff')}")
        report["switch"] = {
            "employee_id": switched["employee_id"],
            "kind": handoff["kind"],
            "reason_code": handoff["reason_code"],
            "from": handoff["from_employee_name"],
            "to": handoff["to_employee_name"],
            "summary_keys": sorted(handoff["summary"]),
            "open_actions": len(handoff["summary"].get("open_actions", [])),
            "pending_questions": len(handoff["summary"].get("pending_questions", [])),
        }
        if switched["employee_id"] != target["id"]:
            raise RuntimeError("conversation still points at the previous employee")
        if not handoff["summary"].get("last_answer"):
            raise RuntimeError("handoff summary has no last answer")

        # 5. the next turn must run as the new employee and see the handoff
        after_switch = client.post(
            f"/api/v1/customer-service/conversations/{conversation_id}/messages",
            headers=admin,
            json={
                "content": "你们好，我接着问：保修怎么申请？",
                "client_message_id": f"{suffix}-m4",
            },
        )
        after_switch.raise_for_status()
        fourth_turn_id = after_switch.json()["current_turn"]["id"]
        conversation = _wait_latest_turn(
            client,
            conversation_id,
            headers=admin,
            turn_id=fourth_turn_id,
        )
        fourth_events = _events(client, conversation_id, fourth_turn_id, headers=admin)
        fourth_assembled = _event(fourth_events, "CONTEXT_ASSEMBLED")
        if fourth_assembled is None:
            raise RuntimeError("turn after switch has no context snapshot")
        fourth_payload = fourth_assembled["payload"]
        report["after_switch"] = {
            "employee_id": fourth_assembled["payload"].get("employee_id"),
            "handoff_id": (fourth_payload.get("handoff") or {}).get("id"),
            "handoff_matches": (fourth_payload.get("handoff") or {}).get("id") == handoff["id"],
            "history_message_count": fourth_payload["history_message_count"],
            "status": conversation["current_turn"]["status"],
        }
        if report["after_switch"]["employee_id"] != target["id"]:
            raise RuntimeError("turn after switch did not run as the new employee")
        if not report["after_switch"]["handoff_matches"]:
            raise RuntimeError("turn after switch did not assemble the handoff")

        # 6. queued turns are causal: the later buyer message stays out of the
        #    earlier turn's context
        causal_response = client.post(
            "/api/v1/customer-service/conversations",
            headers=admin,
            json={
                "business_unit_id": unit,
                "employee_id": first["id"],
                "requester_ref": f"runtime-acceptance-causal-{suffix}",
                "channel": "web_form",
            },
        )
        causal_response.raise_for_status()
        causal_id = causal_response.json()["id"]
        causal_turn_ids: list[str] = []
        for index, content in enumerate(("订单 AB-9001 一直没发货", "另外，能开发票吗？")):
            response = client.post(
                f"/api/v1/customer-service/conversations/{causal_id}/messages",
                headers=admin,
                json={
                    "content": content,
                    "client_message_id": f"{suffix}-causal-{index}",
                },
            )
            response.raise_for_status()
            causal_turn_ids.append(response.json()["current_turn"]["id"])
        _wait_latest_turn(
            client,
            causal_id,
            headers=admin,
            turn_id=causal_turn_ids[-1],
        )
        causal_view = client.get(
            f"/api/v1/customer-service/conversations/{causal_id}",
            headers=admin,
        ).json()
        buyer_sequence = {
            message["turn_id"]: message["sequence"]
            for message in causal_view["messages"]
            if message["role"] == "BUYER" and message.get("turn_id")
        }
        report["causality"] = {}
        for turn_id in causal_turn_ids:
            events = _events(client, causal_id, turn_id, headers=admin)
            assembled = _event(events, "CONTEXT_ASSEMBLED")
            if assembled is None:
                raise RuntimeError(f"queued turn {turn_id} has no context snapshot")
            own_sequence = buyer_sequence[turn_id]
            history_sequences = assembled["payload"]["history_sequences"]
            if any(sequence >= own_sequence for sequence in history_sequences):
                raise RuntimeError(
                    "a turn saw a message sent after it: "
                    f"own={own_sequence} history={history_sequences}"
                )
            report["causality"][turn_id] = {
                "own_sequence": own_sequence,
                "history_sequences": history_sequences,
            }

        # 7. two first messages at the same instant share one ticket
        race_response = client.post(
            "/api/v1/customer-service/conversations",
            headers=admin,
            json={
                "business_unit_id": unit,
                "employee_id": first["id"],
                "requester_ref": f"runtime-acceptance-race-{suffix}",
                "channel": "web_form",
            },
        )
        race_response.raise_for_status()
        race_id = race_response.json()["id"]
        race: dict[str, Any] = {}

        def _race_send(tag: str) -> None:
            response = client.post(
                f"/api/v1/customer-service/conversations/{race_id}/messages",
                headers=admin,
                json={
                    "content": f"并发问题{tag}：这个保温杯能保温多久？",
                    "client_message_id": f"{suffix}-race-{tag}",
                },
            )
            body = response.json()
            current = body.get("current_turn") or {}
            race[tag] = {
                "status": response.status_code,
                "turn_id": current.get("id"),
                "ticket_id": body.get("current_ticket_id"),
                "code": body.get("code"),
            }

        threads = [threading.Thread(target=_race_send, args=(tag,)) for tag in ("a", "b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        report["concurrent_first_messages"] = race
        if any(item["status"] != 202 for item in race.values()):
            raise RuntimeError(f"a concurrent first message was refused: {race}")
        if race["a"]["ticket_id"] != race["b"]["ticket_id"]:
            raise RuntimeError(f"concurrent first messages made two tickets: {race}")
        if race["a"]["turn_id"] == race["b"]["turn_id"]:
            raise RuntimeError(f"concurrent first messages shared one turn: {race}")
        # Which of the two threads won the race decides the turn order, so wait
        # on the latest turn only: turns run one at a time, so both are done.
        _wait_latest_turn(client, race_id, headers=admin)
        for tag, item in race.items():
            events = _events(client, race_id, item["turn_id"], headers=admin)
            status = _turn_status_from_events(events)
            if status is None:
                raise RuntimeError(f"concurrent turn {tag} never finished: {events}")
            item["status_at_end"] = status

        # 8. an employee of another business unit cannot receive the handoff
        foreign_admin = _headers(
            f"runtime-acceptance-admin-{suffix}",
            "admin",
            "bu_acceptance",
        )
        foreign_response = client.get(
            "/api/v1/digital-employees",
            params={"business_unit_id": "bu_acceptance"},
            headers=foreign_admin,
        )
        foreign_response.raise_for_status()
        foreign = next(
            (
                employee
                for employee in foreign_response.json()
                if employee["status"] == "ACTIVE" and employee["domain"] == "customer_service"
            ),
            None,
        )
        if foreign is None:
            report["cross_unit_switch"] = "no active employee in bu_acceptance"
        else:
            cross_unit = client.post(
                f"/api/v1/customer-service/conversations/{conversation_id}/employee",
                headers=admin,
                json={"employee_id": foreign["id"], "reason": "acceptance"},
            )
            report["cross_unit_switch"] = {
                "status": cross_unit.status_code,
                "code": _problem_code(cross_unit),
            }
            if (
                cross_unit.status_code != 400
                or _problem_code(cross_unit) != "HANDOFF_EMPLOYEE_UNIT_MISMATCH"
            ):
                raise RuntimeError(
                    f"cross-business-unit switch was not refused: {report['cross_unit_switch']}"
                )

        # 9. an employee of another domain (HR here) cannot take the handoff
        #    either, even inside the same business unit
        same_unit = client.get(
            "/api/v1/digital-employees",
            params={"business_unit_id": unit},
            headers=admin,
        )
        same_unit.raise_for_status()
        other_domain = next(
            (
                employee
                for employee in same_unit.json()
                if employee["status"] == "ACTIVE" and employee["domain"] != "customer_service"
            ),
            None,
        )
        if other_domain is None:
            report["cross_domain_switch"] = "no active non-customer employee"
        else:
            cross_domain = client.post(
                f"/api/v1/customer-service/conversations/{conversation_id}/employee",
                headers=admin,
                json={"employee_id": other_domain["id"], "reason": "acceptance"},
            )
            report["cross_domain_switch"] = {
                "status": cross_domain.status_code,
                "code": _problem_code(cross_domain),
                "domain": other_domain["domain"],
            }
            if (
                cross_domain.status_code != 409
                or _problem_code(cross_domain) != "EMPLOYEE_DOMAIN_MISMATCH"
            ):
                raise RuntimeError(
                    f"cross-domain switch was not refused: {report['cross_domain_switch']}"
                )

        # 10. pre-M1 conversations still render
        listing = client.get(
            "/api/v1/customer-service/conversations",
            params={"business_unit_id": unit},
            headers=admin,
        )
        listing.raise_for_status()
        legacy = next(
            (
                item
                for item in listing.json()["items"]
                if item["id"] != conversation_id and item["latest_handoff"] is None
            ),
            None,
        )
        if legacy is None:
            report["legacy"] = "no pre-M1 conversation in this business unit"
        else:
            detail = client.get(
                f"/api/v1/customer-service/conversations/{legacy['id']}",
                headers=admin,
            )
            detail.raise_for_status()
            report["legacy"] = {
                "conversation_id": legacy["id"],
                "messages": len(detail.json()["messages"]),
                "latest_handoff": detail.json()["latest_handoff"],
                "replayed": detail.json()["replayed"],
            }

        print(json.dumps(report, ensure_ascii=False, indent=2))


def _problem_code(response: httpx.Response) -> str | None:
    try:
        return cast("str | None", response.json().get("code"))
    except ValueError:
        return None


if __name__ == "__main__":
    main()

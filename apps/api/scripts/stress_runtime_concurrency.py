#!/usr/bin/env python3
"""Concurrency stress for the conversation runtime (M4 follow-up).

The acceptance suites prove single-request behaviour. This script attacks the
two places where requests race each other on the live stack:

1. **Takeover vs. in-flight turn (RT-30).** An operator takes the conversation
   while the buyer's turn is being dispatched. Whatever the interleaving, the
   turn must end terminal, a cancelled turn must never carry an assistant
   answer, and no answer may be written after the human owned the conversation.
2. **Duplicate and concurrent buyer messages.** The same
   ``client_message_id`` submitted twice must produce one turn and one buyer
   message; two different messages must both be accepted with distinct turn
   sequences and a single initial ticket.
3. **Handoff vs. in-flight turn.** A supervisor switches the conversation to
   another digital employee while the worker writes to the same turn. The turn
   must finish promptly, the event log of every turn must keep unique and
   contiguous sequences, and the conversation must end on the new employee.

Every assertion reads the real PostgreSQL database through psycopg; the
requests go over HTTP to the running API and worker, exactly as an operator or
connector would.

Usage:
    uv run python scripts/stress_runtime_concurrency.py [base_url] [-n 20]

``ACCEPTANCE_DATABASE_URL`` overrides the default
``postgresql://ticket_agent:ticket_agent@127.0.0.1:5432/ticket_agent``.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import psycopg
from acceptance_skill_contract import (
    _activate,
    _create_employee,
    _headers,
    _seed_aftersales_knowledge,
)

DATABASE_URL = os.getenv(
    "ACCEPTANCE_DATABASE_URL",
    "postgresql://ticket_agent:ticket_agent@127.0.0.1:5432/ticket_agent",
)
ACTIVE_STATUSES = ("PENDING", "RUNNING")
QUESTION = "保温杯内胆是什么材质，能保温多久？"


@dataclass
class Stats:
    cancelled_turns: int = 0
    completed_before_takeover: int = 0
    takeover_version_retries: int = 0
    handoffs: int = 0
    deadlock_probes: int = 0
    throttled_requests: int = 0
    iterations: int = 0
    checks: list[str] = field(default_factory=list)


def _request(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    stats: Stats,
    **kwargs: Any,
) -> httpx.Response:
    """Send one request, waiting out 429s instead of failing the stress run."""
    deadline = time.monotonic() + 120
    while True:
        response = client.request(method, url, **kwargs)
        if response.status_code != 429:
            return response
        stats.throttled_requests += 1
        context = response.json().get("context") or {}
        wait = float(context.get("retry_after_seconds") or 5)
        if time.monotonic() + wait > deadline:
            raise RuntimeError(f"rate limit did not clear: {response.text}")
        time.sleep(wait)


def _create_conversation(
    client: httpx.Client,
    headers: dict[str, str],
    employee_id: str,
    requester_ref: str,
    *,
    stats: Stats,
) -> str:
    response = _request(
        client,
        "POST",
        "/api/v1/customer-service/conversations",
        stats=stats,
        headers=headers,
        json={
            "business_unit_id": headers["X-Business-Unit-Id"],
            "employee_id": employee_id,
            "requester_ref": requester_ref,
        },
    )
    response.raise_for_status()
    return cast(str, response.json()["id"])


def _send(
    client: httpx.Client,
    headers: dict[str, str],
    conversation_id: str,
    content: str,
    *,
    stats: Stats,
    client_message_id: str | None = None,
) -> httpx.Response:
    payload: dict[str, Any] = {"content": content}
    if client_message_id is not None:
        payload["client_message_id"] = client_message_id
    return _request(
        client,
        "POST",
        f"/api/v1/customer-service/conversations/{conversation_id}/messages",
        stats=stats,
        headers=headers,
        json=payload,
    )


def _takeover(
    client: httpx.Client,
    headers: dict[str, str],
    conversation_id: str,
    *,
    stats: Stats,
    deadline_seconds: float = 10.0,
) -> httpx.Response:
    """Take over, refreshing ``expected_version`` like an operator would.

    A buyer message bumps the conversation version, so a takeover racing it
    legitimately gets ``CONVERSATION_VERSION_CONFLICT``; the workbench reloads
    and retries.
    """
    deadline = time.monotonic() + deadline_seconds
    last: httpx.Response | None = None
    while time.monotonic() < deadline:
        current = _request(
            client,
            "GET",
            f"/api/v1/customer-service/conversations/{conversation_id}",
            stats=stats,
            headers=headers,
        )
        current.raise_for_status()
        response = _request(
            client,
            "POST",
            f"/api/v1/customer-service/conversations/{conversation_id}/takeover",
            stats=stats,
            headers=headers,
            json={"expected_version": current.json()["version"]},
        )
        last = response
        if response.status_code == 200:
            return response
        body = response.json()
        if response.status_code == 409 and body.get("code") == (
            "CONVERSATION_VERSION_CONFLICT"
        ):
            stats.takeover_version_retries += 1
            time.sleep(0.02)
            continue
        raise RuntimeError(
            f"takeover rejected: {response.status_code} {response.text}"
        )
    raise RuntimeError(
        f"takeover kept conflicting: {last.text if last is not None else ''}"
    )


def _turns(conversation_id: str) -> list[dict[str, Any]]:
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        rows = connection.execute(
            """
            SELECT id, status, assistant_message_id, completed_at, sequence
              FROM conversation_turns
             WHERE conversation_id = %s
             ORDER BY sequence
            """,
            (str(UUID(conversation_id)),),
        ).fetchall()
    return [
        {
            "id": str(row[0]),
            "status": row[1],
            "assistant_message_id": str(row[2]) if row[2] else None,
            "completed_at": row[3],
            "sequence": row[4],
        }
        for row in rows
    ]


def _messages(conversation_id: str) -> list[dict[str, Any]]:
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        rows = connection.execute(
            """
            SELECT id, role, content, sequence, turn_id, created_at
              FROM customer_messages
             WHERE conversation_id = %s
             ORDER BY sequence
            """,
            (str(UUID(conversation_id)),),
        ).fetchall()
    return [
        {
            "id": str(row[0]),
            "role": row[1],
            "content": row[2],
            "sequence": row[3],
            "turn_id": str(row[4]) if row[4] else None,
            "created_at": row[5],
        }
        for row in rows
    ]


def _out_of_order_answers(conversation_id: str) -> int:
    """Assistant answers of turns that finished after the human took over."""
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        row = connection.execute(
            """
            SELECT count(*)
              FROM customer_messages m
              JOIN conversation_turns t ON t.id = m.turn_id
              JOIN customer_conversations c ON c.id = m.conversation_id
             WHERE m.conversation_id = %s
               AND m.role = 'ASSISTANT'
               AND c.assigned_at IS NOT NULL
               AND t.completed_at IS NOT NULL
               AND t.completed_at > c.assigned_at
            """,
            (str(UUID(conversation_id)),),
        ).fetchone()
    return int(row[0]) if row else 0


def _wait_quiet(conversation_id: str, *, timeout: float = 90.0) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    while True:
        turns = _turns(conversation_id)
        if not any(turn["status"] in ACTIVE_STATUSES for turn in turns):
            return turns
        if time.monotonic() >= deadline:
            statuses = [turn["status"] for turn in turns]
            raise AssertionError(
                f"conversation {conversation_id} still has active turns: {statuses}"
            )
        time.sleep(0.2)


def _turn_event_sequences(conversation_id: str) -> dict[str, list[int]]:
    """Every turn's event sequences, in order."""
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        rows = connection.execute(
            """
            SELECT e.turn_id, e.sequence
              FROM conversation_turn_events e
              JOIN conversation_turns t ON t.id = e.turn_id
             WHERE t.conversation_id = %s
             ORDER BY e.turn_id, e.sequence
            """,
            (str(UUID(conversation_id)),),
        ).fetchall()
    grouped: dict[str, list[int]] = {}
    for turn_id, sequence in rows:
        grouped.setdefault(str(turn_id), []).append(sequence)
    return grouped


def _conversation_employee(conversation_id: str) -> str | None:
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        row = connection.execute(
            "SELECT employee_id FROM customer_conversations WHERE id = %s",
            (str(UUID(conversation_id)),),
        ).fetchone()
    return str(row[0]) if row and row[0] else None


def _ticket_workflow(conversation_id: str) -> str | None:
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        row = connection.execute(
            """
            SELECT t.workflow_state
              FROM customer_conversations c
              JOIN tickets t ON t.id = c.current_ticket_id
             WHERE c.id = %s
            """,
            (str(UUID(conversation_id)),),
        ).fetchone()
    return cast(str, row[0]) if row else None


def _archive(
    client: httpx.Client,
    headers: dict[str, str],
    conversation_id: str,
    *,
    stats: Stats,
) -> None:
    current = _request(
        client,
        "GET",
        f"/api/v1/customer-service/conversations/{conversation_id}",
        stats=stats,
        headers=headers,
    )
    ticket_id = current.json().get("current_ticket_id") if current.is_success else None
    for url in (
        f"/api/v1/customer-service/conversations/{conversation_id}/archive-test-data",
        *( [f"/api/v1/tickets/{ticket_id}/archive-test-data"] if ticket_id else [] ),
    ):
        _request(client, "POST", url, stats=stats, headers=headers)


def _check(condition: bool, message: str, stats: Stats) -> None:
    if not condition:
        raise AssertionError(message)
    stats.checks.append(message)


def _takeover_race(
    client: httpx.Client,
    headers: dict[str, str],
    employee_id: str,
    *,
    stats: Stats,
) -> None:
    suffix = uuid4().hex[:8]
    conversation_id = _create_conversation(
        client,
        headers,
        employee_id,
        f"stress-takeover-{suffix}",
        stats=stats,
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            send_future = pool.submit(
                _send,
                client,
                headers,
                conversation_id,
                QUESTION,
                stats=stats,
            )
            takeover_future = pool.submit(
                _takeover,
                client,
                headers,
                conversation_id,
                stats=stats,
            )
            sent = send_future.result()
            taken = takeover_future.result()
        _check(sent.status_code == 202, "buyer message accepted during takeover", stats)
        _check(taken.status_code == 200, "takeover accepted during dispatch", stats)

        turns = _wait_quiet(conversation_id)
        active = [turn["status"] for turn in turns if turn["status"] in ACTIVE_STATUSES]
        _check(not active, "no turn stays PENDING/RUNNING after takeover", stats)
        cancelled = [turn for turn in turns if turn["status"] == "CANCELLED"]
        stats.cancelled_turns += len(cancelled)
        stats.completed_before_takeover += sum(
            turn["status"] == "COMPLETED" for turn in turns
        )
        _check(
            all(turn["assistant_message_id"] is None for turn in cancelled),
            "cancelled turns never carry an assistant answer",
            stats,
        )
        _check(
            _out_of_order_answers(conversation_id) == 0,
            "no answer is written after the human took over",
            stats,
        )
        workflow = _ticket_workflow(conversation_id)
        # Message first and finished before takeover: COMPLETED. Message
        # first and cancelled mid-flight: TAKEN_OVER. Takeover first: the new
        # ticket starts as NEEDS_HUMAN.
        _check(
            workflow in {None, "COMPLETED", "TAKEN_OVER", "NEEDS_HUMAN"},
            f"ticket state matches the race outcome ({workflow})",
            stats,
        )

        before = _messages(conversation_id)
        assistant_before = sum(m["role"] == "ASSISTANT" for m in before)
        silent = _send(client, headers, conversation_id, "你好", stats=stats)
        _check(silent.status_code == 202, "buyer can still write after takeover", stats)
        view = silent.json()
        _check(
            view.get("current_turn", {}).get("status") == "NEEDS_HUMAN",
            "message during human ownership waits for the human",
            stats,
        )
        after = _messages(conversation_id)
        _check(
            sum(m["role"] == "ASSISTANT" for m in after) == assistant_before,
            "the digital employee stays silent while the human owns the chat",
            stats,
        )

        for turn in cancelled:
            retried = _request(
                client,
                "POST",
                f"/api/v1/customer-service/turns/{turn['id']}/retry",
                stats=stats,
                headers=headers,
            )
            _check(
                retried.status_code == 409,
                "a cancelled turn cannot be retried back to life",
                stats,
            )
    finally:
        _wait_quiet(conversation_id)
        _archive(client, headers, conversation_id, stats=stats)
    stats.iterations += 1


def _duplicate_message_race(
    client: httpx.Client,
    headers: dict[str, str],
    employee_id: str,
    *,
    stats: Stats,
) -> None:
    suffix = uuid4().hex[:8]
    conversation_id = _create_conversation(
        client,
        headers,
        employee_id,
        f"stress-duplicate-{suffix}",
        stats=stats,
    )
    client_message_id = f"stress-dup-{suffix}"
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(
                pool.map(
                    lambda _: _send(
                        client,
                        headers,
                        conversation_id,
                        QUESTION,
                        stats=stats,
                        client_message_id=client_message_id,
                    ),
                    range(2),
                )
            )
        _check(
            all(response.status_code == 202 for response in responses),
            "both duplicate submissions are accepted",
            stats,
        )
        turns = _wait_quiet(conversation_id)
        _check(len(turns) == 1, "duplicate client_message_id yields one turn", stats)
        messages = [m for m in _messages(conversation_id) if m["role"] == "BUYER"]
        _check(
            len(messages) == 1,
            "duplicate client_message_id yields one buyer message",
            stats,
        )
        _check(
            {response.json()["current_turn"]["id"] for response in responses}
            == {turns[0]["id"]},
            "duplicate submissions return the same turn",
            stats,
        )
    finally:
        _wait_quiet(conversation_id)
        _archive(client, headers, conversation_id, stats=stats)


def _concurrent_messages_race(
    client: httpx.Client,
    headers: dict[str, str],
    employee_id: str,
    *,
    stats: Stats,
) -> None:
    suffix = uuid4().hex[:8]
    conversation_id = _create_conversation(
        client,
        headers,
        employee_id,
        f"stress-concurrent-{suffix}",
        stats=stats,
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(
                    _send,
                    client,
                    headers,
                    conversation_id,
                    content,
                    stats=stats,
                )
                for content in (
                    "保温杯内胆是什么材质？",
                    "保温杯能保温多久？",
                )
            ]
            responses = [future.result() for future in futures]
        _check(
            all(response.status_code == 202 for response in responses),
            "two concurrent messages are both accepted",
            stats,
        )
        _check(
            len({response.json()["current_ticket_id"] for response in responses}) == 1,
            "concurrent first messages share one ticket",
            stats,
        )
        turns = _wait_quiet(conversation_id)
        _check(len(turns) == 2, "two concurrent messages create two turns", stats)
        sequences = [turn["sequence"] for turn in turns]
        _check(
            len(sequences) == len(set(sequences)),
            "concurrent messages get distinct turn sequences",
            stats,
        )
        _check(
            all(turn["status"] in {"COMPLETED", "NEEDS_HUMAN", "FAILED_RETRYABLE"}
                for turn in turns),
            "concurrent turns reach a terminal or retryable state",
            stats,
        )
    finally:
        _wait_quiet(conversation_id)
        _archive(client, headers, conversation_id, stats=stats)


def _handoff_race(
    client: httpx.Client,
    headers: dict[str, str],
    employee_id: str,
    other_employee_id: str,
    *,
    stats: Stats,
) -> None:
    """Hand the conversation over while the buyer's turn is being dispatched.

    The switch appends a ``HANDOFF_CREATED`` event to the very turn the worker
    is writing to. Both writers must agree on the event sequence, and the pair
    may deadlock; either way the turn must finish promptly instead of waiting
    for the lease to expire.
    """
    suffix = uuid4().hex[:8]
    conversation_id = _create_conversation(
        client,
        headers,
        employee_id,
        f"stress-handoff-{suffix}",
        stats=stats,
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            send_future = pool.submit(
                _send,
                client,
                headers,
                conversation_id,
                QUESTION,
                stats=stats,
            )
            switch_future = pool.submit(
                _request,
                client,
                "POST",
                f"/api/v1/customer-service/conversations/{conversation_id}/employee",
                stats=stats,
                headers=headers,
                json={
                    "employee_id": other_employee_id,
                    "reason": "stress handoff race",
                },
            )
            sent = send_future.result()
            switched = switch_future.result()
        _check(sent.status_code == 202, "buyer message accepted during handoff", stats)
        _check(switched.status_code == 200, "handoff accepted during dispatch", stats)
        stats.handoffs += 1
        _check(
            _conversation_employee(conversation_id) == other_employee_id,
            "handoff moves the conversation to the new employee",
            stats,
        )

        turns = _wait_quiet(conversation_id, timeout=45.0)
        _check(
            all(turn["status"] not in ACTIVE_STATUSES for turn in turns),
            "no turn waits for the lease after a handoff",
            stats,
        )
        _check(
            all(
                turn["status"]
                in {"COMPLETED", "NEEDS_HUMAN", "FAILED_TERMINAL", "CANCELLED"}
                for turn in turns
            ),
            "a handed-over turn reaches a final state",
            stats,
        )
        sequences = _turn_event_sequences(conversation_id)
        _check(
            all(
                values == list(range(1, len(values) + 1))
                for values in sequences.values()
            ),
            "turn event sequences stay unique and contiguous across a handoff",
            stats,
        )
        _check(
            all(
                turn["id"] in sequences for turn in turns
            ),
            "every turn keeps its event log",
            stats,
        )
    finally:
        _wait_quiet(conversation_id, timeout=45.0)
        _archive(client, headers, conversation_id, stats=stats)


def _handoff_deadlock_probe(
    client: httpx.Client,
    headers: dict[str, str],
    employee_id: str,
    other_employee_id: str,
    *,
    stats: Stats,
) -> None:
    """Force the handoff/worker lock cycle and require the API to absorb it.

    Locks a running turn from a probe transaction, then asks the API to hand
    the conversation over: the switch takes the conversation lock and waits for
    the turn, the probe then takes the conversation lock and waits for the turn
    — a cycle PostgreSQL breaks by aborting one side. Before the retry existed
    an aborted switch surfaced as ``500 DATABASE_ERROR``; now the request must
    still end in 200 once the probe releases its lock.
    """
    suffix = uuid4().hex[:8]
    conversation_id = _create_conversation(
        client,
        headers,
        employee_id,
        f"stress-deadlock-{suffix}",
        stats=stats,
    )
    try:
        sent = _send(client, headers, conversation_id, QUESTION, stats=stats)
        _check(sent.status_code == 202, "buyer message accepted before the probe", stats)
        deadline = time.monotonic() + 30
        while True:
            turns = _turns(conversation_id)
            if any(turn["status"] == "RUNNING" for turn in turns):
                break
            if time.monotonic() >= deadline:
                raise AssertionError("the probe needs a RUNNING turn")
            time.sleep(0.2)
        turn_id = next(turn["id"] for turn in turns if turn["status"] == "RUNNING")

        probe = psycopg.connect(DATABASE_URL)
        try:
            probe.execute(
                "SELECT id FROM conversation_turns WHERE id = %s FOR UPDATE",
                (turn_id,),
            )
            with ThreadPoolExecutor(max_workers=1) as pool:
                switch_future = pool.submit(
                    _request,
                    client,
                    "POST",
                    f"/api/v1/customer-service/conversations/{conversation_id}/employee",
                    stats=stats,
                    headers=headers,
                    json={
                        "employee_id": other_employee_id,
                        "reason": "forced deadlock probe",
                    },
                )
                # Let the switch take the conversation lock and block on our
                # turn lock, then close the cycle from this side.
                time.sleep(0.5)
                try:
                    probe.execute(
                        "SELECT id FROM customer_conversations WHERE id = %s"
                        " FOR UPDATE",
                        (conversation_id,),
                    )
                    probe.rollback()
                except psycopg.errors.DeadlockDetected:
                    probe.rollback()
                stats.deadlock_probes += 1
                switched = switch_future.result()
        finally:
            probe.close()

        _check(
            switched.status_code == 200,
            "a handoff that lost a deadlock is retried to success",
            stats,
        )
        _check(
            _conversation_employee(conversation_id) == other_employee_id,
            "the retried handoff still moved the conversation",
            stats,
        )
        turns = _wait_quiet(conversation_id, timeout=45.0)
        _check(
            all(turn["status"] not in ACTIVE_STATUSES for turn in turns),
            "the forced deadlock leaves no turn waiting for the lease",
            stats,
        )
        sequences = _turn_event_sequences(conversation_id)
        _check(
            all(
                values == list(range(1, len(values) + 1))
                for values in sequences.values()
            ),
            "turn event sequences stay unique and contiguous after a forced deadlock",
            stats,
        )
    finally:
        _wait_quiet(conversation_id, timeout=45.0)
        _archive(client, headers, conversation_id, stats=stats)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", nargs="?", default="http://127.0.0.1:8000")
    parser.add_argument("-n", "--iterations", type=int, default=20)
    parser.add_argument(
        "--force-deadlocks",
        action="store_true",
        help="also inject the handoff/worker lock cycle deterministically",
    )
    args = parser.parse_args()

    suffix = uuid4().hex[:8]
    headers = _headers(f"stress-agent-{suffix}", "admin", "bu_demo")
    stats = Stats()
    started = time.monotonic()
    with httpx.Client(base_url=args.base_url, timeout=60.0) as client:
        employee_id = _create_employee(
            client, headers, f"stress_agent_{suffix}", "并发压测客服"
        )
        _seed_aftersales_knowledge(client, headers, employee_id, suffix)
        _activate(client, headers, employee_id)
        other_employee_id = _create_employee(
            client, headers, f"stress_agent_b_{suffix}", "并发压测客服 B"
        )
        _seed_aftersales_knowledge(client, headers, other_employee_id, f"{suffix}b")
        _activate(client, headers, other_employee_id)

        for iteration in range(args.iterations):
            try:
                _takeover_race(client, headers, employee_id, stats=stats)
            except Exception as error:
                print(
                    f"iteration {iteration + 1} failed: {error}",
                    file=sys.stderr,
                )
                raise
            print(
                f"iteration {iteration + 1}/{args.iterations} ok "
                f"(cancelled so far: {stats.cancelled_turns}, "
                f"completed-before-takeover: {stats.completed_before_takeover})"
            )

        for iteration in range(max(3, args.iterations // 2)):
            try:
                _handoff_race(
                    client,
                    headers,
                    employee_id,
                    other_employee_id,
                    stats=stats,
                )
            except Exception as error:
                print(
                    f"handoff iteration {iteration + 1} failed: {error}",
                    file=sys.stderr,
                )
                raise
            print(f"handoff iteration {iteration + 1} ok")

        if args.force_deadlocks:
            for iteration in range(3):
                _handoff_deadlock_probe(
                    client,
                    headers,
                    employee_id,
                    other_employee_id,
                    stats=stats,
                )
                print(f"deadlock probe {iteration + 1} ok")

        _duplicate_message_race(client, headers, employee_id, stats=stats)
        _concurrent_messages_race(client, headers, employee_id, stats=stats)

    elapsed = time.monotonic() - started
    unique_checks = list(dict.fromkeys(stats.checks))
    print()
    for message in unique_checks:
        print(f"  - {message}")
    print(
        f"\n{stats.iterations} takeover races, {stats.handoffs} handoff races, "
        f"{stats.deadlock_probes} forced deadlock probes, "
        f"{stats.cancelled_turns} cancelled turns, "
        f"{stats.completed_before_takeover} completed before takeover, "
        f"{stats.takeover_version_retries} version-conflict retries, "
        f"{stats.throttled_requests} rate-limit waits, {elapsed:.1f}s"
    )
    print(f"ALL CHECKS PASSED ({len(unique_checks)} kinds, {len(stats.checks)} assertions)")


if __name__ == "__main__":
    main()

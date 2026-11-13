"""Real-PostgreSQL races for roster publishing, cloning and assignment.

SQLite serialises writers, so it cannot prove the partial unique indexes or the
deterministic presence locks. These tests only run when ``TEST_POSTGRES_URL``
points at a migrated PostgreSQL database.
"""

from __future__ import annotations

import os
import threading
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from ticket_agent.customer_service.models import (
    AgentPresence,
    CustomerConversation,
)
from ticket_agent.scheduling.models import (
    AgentRoster,
    AgentRosterEntry,
    AgentShiftTemplate,
)
from ticket_agent.scheduling.service import clone_roster, publish
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.tickets.models import Ticket

POSTGRES_URL = os.getenv("TEST_POSTGRES_URL")


def _week_start() -> date:
    today = datetime.now(UTC).date()
    return today - timedelta(days=today.weekday())


def _cleanup(engine, unit: str) -> None:
    with Session(engine) as cleanup:
        roster_ids = select(AgentRoster.id).where(
            AgentRoster.business_unit_id == unit
        )
        cleanup.execute(
            delete(AgentRosterEntry).where(
                AgentRosterEntry.roster_id.in_(roster_ids)
            )
        )
        cleanup.execute(
            delete(AgentRoster).where(AgentRoster.business_unit_id == unit)
        )
        cleanup.execute(
            delete(AgentShiftTemplate).where(
                AgentShiftTemplate.business_unit_id == unit
            )
        )
        cleanup.execute(
            delete(AgentPresence).where(AgentPresence.business_unit_id == unit)
        )
        cleanup.execute(
            delete(CustomerConversation).where(
                CustomerConversation.business_unit_id == unit
            )
        )
        cleanup.execute(delete(Ticket).where(Ticket.business_unit_id == unit))
        cleanup.commit()


def _seed_draft(engine, unit: str, agent_id: str) -> UUID:
    week = _week_start()
    shift = AgentShiftTemplate(
        id=uuid4(),
        business_unit_id=unit,
        name="PG 并发班",
        start_local=time(0, 0),
        end_local=time(23, 59),
        status="ACTIVE",
        version=1,
        created_by="pg-test",
    )
    roster_id = uuid4()
    roster = AgentRoster(
        id=roster_id,
        business_unit_id=unit,
        week_start=week,
        timezone="Asia/Shanghai",
        status="DRAFT",
        version=1,
        created_by="pg-test",
    )
    with Session(engine) as setup:
        setup.add(shift)
        setup.add(roster)
        setup.flush()
        for offset in range(7):
            shift_date = week + timedelta(days=offset)
            start_at = datetime.combine(
                shift_date, time(0, 0), tzinfo=UTC
            )
            setup.add(
                AgentRosterEntry(
                    id=uuid4(),
                    roster_id=roster.id,
                    shift_template_id=shift.id,
                    agent_id=agent_id,
                    agent_display_name=agent_id,
                    shift_date=shift_date,
                    start_at=start_at,
                    end_at=start_at + timedelta(hours=23, minutes=59),
                    shift_name="PG 并发班",
                    shift_version=1,
                    snapshot_json={
                        "shift_name": "PG 并发班",
                        "timezone": "Asia/Shanghai",
                    },
                )
            )
        setup.commit()
    return roster_id


@pytest.mark.skipif(not POSTGRES_URL, reason="TEST_POSTGRES_URL is not configured")
def test_concurrent_publish_keeps_one_published_row() -> None:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    unit = f"bu_sched_pg_pub_{uuid4().hex[:8]}"
    roster_id = _seed_draft(engine, unit, "pg-agent")
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []
    results: list[object] = []
    lock = threading.Lock()

    def worker() -> None:
        worker_engine = create_engine(POSTGRES_URL)
        try:
            with Session(worker_engine) as session:
                barrier.wait(timeout=10)
                result = publish(
                    session,
                    business_unit_id=unit,
                    roster_id=roster_id,
                    actor_id="pg-admin",
                )
                session.commit()
                with lock:
                    results.append(result)
        except BaseException as exc:  # pragma: no cover - surfaced below
            with lock:
                errors.append(exc)
        finally:
            worker_engine.dispose()

    try:
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert not errors, errors
        assert len(results) == 2
        with Session(engine) as verify:
            published = verify.scalar(
                select(func.count())
                .select_from(AgentRoster)
                .where(
                    AgentRoster.business_unit_id == unit,
                    AgentRoster.status == "PUBLISHED",
                )
            )
            drafts = verify.scalar(
                select(func.count())
                .select_from(AgentRoster)
                .where(
                    AgentRoster.business_unit_id == unit,
                    AgentRoster.status == "DRAFT",
                )
            )
            assert published == 1
            assert drafts == 0
    finally:
        _cleanup(engine, unit)
        engine.dispose()


@pytest.mark.skipif(not POSTGRES_URL, reason="TEST_POSTGRES_URL is not configured")
def test_concurrent_clone_creates_one_draft() -> None:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    unit = f"bu_sched_pg_clone_{uuid4().hex[:8]}"
    roster_id = _seed_draft(engine, unit, "pg-agent")
    with Session(engine) as setup:
        roster = setup.get(AgentRoster, roster_id)
        assert roster is not None
        roster.status = "PUBLISHED"
        roster.published_by = "pg-admin"
        roster.published_at = datetime.now(UTC)
        setup.commit()

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []
    successes: list[object] = []
    lock = threading.Lock()

    def worker() -> None:
        worker_engine = create_engine(POSTGRES_URL)
        try:
            with Session(worker_engine) as session:
                barrier.wait(timeout=10)
                try:
                    result = clone_roster(
                        session,
                        business_unit_id=unit,
                        source_roster_id=roster_id,
                        actor_id="pg-admin",
                    )
                    session.commit()
                    with lock:
                        successes.append(result)
                except ApiProblem as exc:
                    session.rollback()
                    with lock:
                        errors.append(exc)
        finally:
            worker_engine.dispose()

    try:
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert len(successes) == 1, (successes, errors)
        assert len(errors) == 1
        assert isinstance(errors[0], ApiProblem)
        assert errors[0].code == "ROSTER_DRAFT_EXISTS"
        with Session(engine) as verify:
            drafts = verify.scalar(
                select(func.count())
                .select_from(AgentRoster)
                .where(
                    AgentRoster.business_unit_id == unit,
                    AgentRoster.status == "DRAFT",
                )
            )
            assert drafts == 1
    finally:
        _cleanup(engine, unit)
        engine.dispose()


@pytest.mark.skipif(not POSTGRES_URL, reason="TEST_POSTGRES_URL is not configured")
def test_concurrent_auto_assign_does_not_exceed_capacity() -> None:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    unit = f"bu_sched_pg_assign_{uuid4().hex[:8]}"
    now = datetime.now(UTC)
    with Session(engine) as setup:
        setup.add(
            AgentPresence(
                agent_id=f"pg-capacity-agent-{uuid4().hex[:6]}",
                display_name="容量坐席",
                business_unit_id=unit,
                status="ONLINE",
                actor_role="agent",
                skills_json=["ecommerce_aftersales"],
                risk_clearance="R2",
                max_conversations=1,
                auto_assign_enabled=True,
                last_seen_at=now,
            )
        )
        for index in range(2):
            ticket_id = uuid4()
            setup.add(
                Ticket(
                    id=ticket_id,
                    business_unit_id=unit,
                    source_system="scheduling_pg",
                    source_ticket_id=f"PG-{uuid4()}",
                    source_channel="web_form",
                    idempotency_key=f"pg-{uuid4()}",
                    request_hash="0" * 64,
                    requester_ref=f"pg-buyer-{index}",
                    subject="并发派班容量工单",
                    body="验证并发派班不超容量。",
                    workflow_state="NEEDS_HUMAN",
                    priority="P2",
                    risk_level="R0",
                    needs_human=True,
                )
            )
            setup.add(
                CustomerConversation(
                    business_unit_id=unit,
                    requester_ref=f"pg-buyer-{index}",
                    channel="web_form",
                    status="ACTIVE",
                    current_ticket_id=ticket_id,
                )
            )
        setup.commit()

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []
    assigned: list[object] = []
    lock = threading.Lock()

    def worker() -> None:
        worker_engine = create_engine(POSTGRES_URL)
        try:
            from ticket_agent.customer_service.service import (
                CustomerConversationService,
            )

            with Session(worker_engine) as session:
                barrier.wait(timeout=10)
                result = CustomerConversationService(session).auto_assign(
                    unit
                )
                with lock:
                    assigned.append(result)
        except BaseException as exc:  # pragma: no cover - surfaced below
            with lock:
                errors.append(exc)
        finally:
            worker_engine.dispose()

    try:
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert not errors, errors
        total_assigned = sum(
            int(getattr(result, "assigned_count", 0)) for result in assigned
        )
        assert total_assigned == 1
        with Session(engine) as verify:
            rows = verify.scalars(
                select(CustomerConversation).where(
                    CustomerConversation.business_unit_id == unit
                )
            ).all()
            assert len([row for row in rows if row.assigned_agent_id]) == 1
            agent = verify.scalar(
                select(AgentPresence).where(
                    AgentPresence.business_unit_id == unit
                )
            )
            assert agent is not None
    finally:
        _cleanup(engine, unit)
        engine.dispose()

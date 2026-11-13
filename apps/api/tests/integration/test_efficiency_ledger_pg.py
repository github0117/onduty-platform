"""Real-PostgreSQL proof that concurrent ledger materialization stays idempotent.

SQLite serialises writers, so it cannot show the unique-constraint race that two
beat workers (or a beat worker plus a manual rebuild) can hit. This test only
runs when ``TEST_POSTGRES_URL`` points at a migrated PostgreSQL database.
"""

import os
import threading
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from ticket_agent.customer_service.models import CustomerConversation
from ticket_agent.efficiency.models import EfficiencyLedgerEntry
from ticket_agent.efficiency.service import materialize
from ticket_agent.tickets.models import Ticket

POSTGRES_URL = os.getenv("TEST_POSTGRES_URL")


@pytest.mark.skipif(not POSTGRES_URL, reason="TEST_POSTGRES_URL is not configured")
def test_concurrent_materialize_creates_one_entry_per_source() -> None:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    unit = f"bu_eff_pg_{uuid4().hex[:8]}"
    now = datetime.now(UTC)
    ticket_id = uuid4()
    conversation_id = uuid4()
    try:
        with Session(engine) as setup:
            setup.add(
                Ticket(
                    id=ticket_id,
                    business_unit_id=unit,
                    source_system="efficiency_pg",
                    source_ticket_id=f"EFF-PG-{uuid4()}",
                    source_channel="web_form",
                    idempotency_key=f"efficiency-pg-{uuid4()}",
                    request_hash="0" * 64,
                    requester_ref="efficiency-customer",
                    subject="效率账本并发验收工单",
                    body="验证并发物化只产生一条账本。",
                    status="RESOLVED",
                    workflow_state="COMPLETED",
                    created_at=now,
                    updated_at=now,
                )
            )
            setup.add(
                CustomerConversation(
                    id=conversation_id,
                    business_unit_id=unit,
                    requester_ref="efficiency-customer",
                    status="RESOLVED",
                    created_at=now,
                    updated_at=now,
                )
            )
            setup.commit()

        barrier = threading.Barrier(2)
        results: list[object] = []
        errors: list[BaseException] = []
        lock = threading.Lock()

        def worker() -> None:
            worker_engine = create_engine(POSTGRES_URL)
            try:
                with Session(worker_engine) as session:
                    barrier.wait(timeout=10)
                    result = materialize(
                        session,
                        business_unit_id=unit,
                        from_at=now,
                        to_at=datetime.now(UTC),
                    )
                    session.commit()
                    with lock:
                        results.append(result)
            except BaseException as exc:  # pragma: no cover - surfaced below
                with lock:
                    errors.append(exc)
            finally:
                worker_engine.dispose()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert not errors, errors
        created = sum(int(getattr(result, "created", 0)) for result in results)
        assert created == 2

        with Session(engine) as verify:
            total = verify.scalar(
                select(func.count())
                .select_from(EfficiencyLedgerEntry)
                .where(EfficiencyLedgerEntry.business_unit_id == unit)
            )
            assert total == 2
            assert (
                verify.scalar(
                    select(func.count())
                    .select_from(EfficiencyLedgerEntry)
                    .where(
                        EfficiencyLedgerEntry.business_unit_id == unit,
                        EfficiencyLedgerEntry.source_type == "TICKET_AUTO_RESOLVED",
                    )
                )
                == 1
            )
    finally:
        with Session(engine) as cleanup:
            cleanup.execute(
                delete(EfficiencyLedgerEntry).where(
                    EfficiencyLedgerEntry.business_unit_id == unit
                )
            )
            cleanup.execute(
                delete(CustomerConversation).where(
                    CustomerConversation.business_unit_id == unit
                )
            )
            cleanup.execute(delete(Ticket).where(Ticket.business_unit_id == unit))
            cleanup.commit()
        engine.dispose()

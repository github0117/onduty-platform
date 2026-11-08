"""Real-PostgreSQL proof that one pending step is claimed exactly once.

``claim_step`` is a conditional ``UPDATE ... WHERE status='PENDING' AND
attempt_count=<observed>``. SQLite serialises writers and cannot show a
concurrent race, so this test only runs against a real PostgreSQL instance.
"""

import os
import threading
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from ticket_agent.workflows.models import WorkflowRun
from ticket_agent.workflows.service import StepSpec, claim_step, start_run

POSTGRES_URL = os.getenv("TEST_POSTGRES_URL")


@pytest.mark.skipif(not POSTGRES_URL, reason="TEST_POSTGRES_URL is not configured")
def test_concurrent_workers_claim_a_step_once() -> None:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    unit = f"bu_workflow_claim_{uuid4().hex[:8]}"
    run_id = None
    try:
        with Session(engine) as setup:
            run, created = start_run(
                setup,
                business_unit_id=unit,
                workflow_type="wf_pg_claim",
                aggregate_type="ticket",
                aggregate_id=uuid4(),
                idempotency_key=f"wf_pg_claim:{uuid4()}",
                steps=[StepSpec("noop", max_attempts=3)],
            )
            setup.commit()
            assert created is True
            run_id = run.id

        barrier = threading.Barrier(2)
        results: list[object] = []
        errors: list[BaseException] = []
        lock = threading.Lock()

        def worker() -> None:
            worker_engine = create_engine(POSTGRES_URL)
            try:
                with Session(worker_engine) as session:
                    barrier.wait(timeout=10)
                    claim = claim_step(session, run_id=run_id)
                    with lock:
                        results.append(claim)
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
        claimed = [result for result in results if result is not None]
        assert len(claimed) == 1

        with Session(engine) as verify:
            run = verify.get(WorkflowRun, run_id)
            assert run is not None
            assert run.status == "RUNNING"
            assert run.current_step == "noop"
    finally:
        if run_id is not None:
            with Session(engine) as cleanup:
                cleanup.execute(delete(WorkflowRun).where(WorkflowRun.id == run_id))
                cleanup.commit()
        engine.dispose()

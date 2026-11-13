from datetime import UTC, datetime

from ticket_agent.efficiency.service import materialize_active_business_units
from ticket_agent.shared.db import system_session


def materialize_efficiency_ledger_job(
    *,
    now: datetime | None = None,
    window_days: int = 2,
) -> dict[str, int]:
    """Materialize the efficiency ledger for recently active business units.

    A two day window covers outcomes that finish slightly after the beat ran,
    while staying well inside the ledger's append-only contract.
    """

    reference = now or datetime.now(UTC)
    with system_session() as session:
        results = materialize_active_business_units(
            session,
            now=reference,
            window_days=window_days,
        )
        session.commit()
    return results

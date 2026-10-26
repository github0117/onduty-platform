from uuid import UUID

from ticket_agent.shared.db import SessionLocal
from ticket_agent.workforce.service import WorkforceTaskService


def execute_workforce_task_job(
    task_id: UUID,
    correlation_id: str,
) -> None:
    with SessionLocal() as session:
        WorkforceTaskService(session).execute(
            task_id,
            correlation_id=correlation_id,
        )

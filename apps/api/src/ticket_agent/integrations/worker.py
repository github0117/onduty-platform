from uuid import UUID

from ticket_agent.integrations.sync import TicketSyncService
from ticket_agent.shared.db import SessionLocal


def sync_ticket_job(ticket_id: UUID, correlation_id: str) -> None:
    with SessionLocal() as session:
        TicketSyncService(session).sync(ticket_id, correlation_id)


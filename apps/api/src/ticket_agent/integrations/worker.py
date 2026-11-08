from uuid import UUID

from ticket_agent.integrations.sync import TicketSyncService
from ticket_agent.shared.db import system_session


def sync_ticket_job(ticket_id: UUID, correlation_id: str) -> None:
    with system_session() as session:
        TicketSyncService(session).sync(ticket_id, correlation_id)


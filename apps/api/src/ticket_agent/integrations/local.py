from uuid import uuid4

from ticket_agent.integrations.types import TicketSyncPayload, TicketSyncResult


class LocalTicketAdapter:
    """Development adapter; records the successful in-platform sync."""

    @property
    def name(self) -> str:
        return "local"

    def sync_ticket(
        self,
        *,
        payload: TicketSyncPayload,
        idempotency_key: str,
    ) -> TicketSyncResult:
        del idempotency_key
        return TicketSyncResult(
            external_request_id=f"local-{payload.external_ticket_id}-{uuid4()}"
        )

    def get_sync_result(
        self,
        *,
        external_ticket_id: str,
        idempotency_key: str,
    ) -> TicketSyncResult | None:
        del external_ticket_id, idempotency_key
        return None


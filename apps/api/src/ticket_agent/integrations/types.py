from dataclasses import dataclass
from typing import Any, Protocol


class TicketIntegrationError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class TicketSyncPayload:
    external_ticket_id: str
    category_primary: str
    category_secondary: str
    priority: str
    risk_level: str
    queue_id: str
    response_text: str
    citations: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "category_primary": self.category_primary,
            "category_secondary": self.category_secondary,
            "priority": self.priority,
            "risk_level": self.risk_level,
            "queue_id": self.queue_id,
            "response_text": self.response_text,
            "citations": self.citations,
        }


@dataclass(frozen=True)
class TicketSyncResult:
    external_request_id: str


class TicketAdapter(Protocol):
    @property
    def name(self) -> str: ...

    def sync_ticket(
        self,
        *,
        payload: TicketSyncPayload,
        idempotency_key: str,
    ) -> TicketSyncResult: ...

    def get_sync_result(
        self,
        *,
        external_ticket_id: str,
        idempotency_key: str,
    ) -> TicketSyncResult | None: ...


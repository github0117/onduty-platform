from urllib.parse import quote

import httpx

from ticket_agent.integrations.types import (
    TicketIntegrationError,
    TicketSyncPayload,
    TicketSyncResult,
)
from ticket_agent.shared.settings import Settings


class HTTPJSONTicketAdapter:
    """Generic JSON-over-HTTP ticket adapter.

    Contract: PUT /tickets/{external_ticket_id} with a stable Idempotency-Key.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self._client = client or httpx.Client(
            timeout=settings.ticket_api_timeout_seconds
        )

    @property
    def name(self) -> str:
        return "http_json"

    def sync_ticket(
        self,
        *,
        payload: TicketSyncPayload,
        idempotency_key: str,
    ) -> TicketSyncResult:
        if not self.settings.ticket_api_base_url:
            raise TicketIntegrationError(
                "TICKET_API_BASE_URL is not configured",
                retryable=False,
            )
        headers = {
            "Idempotency-Key": idempotency_key,
            "Content-Type": "application/json",
        }
        if self.settings.ticket_api_key:
            headers["Authorization"] = f"Bearer {self.settings.ticket_api_key}"
        try:
            response = self._client.put(
                (
                    f"{self.settings.ticket_api_base_url.rstrip('/')}/tickets/"
                    f"{quote(payload.external_ticket_id, safe='')}"
                ),
                headers=headers,
                json=payload.as_dict(),
            )
        except httpx.HTTPError as exc:
            raise TicketIntegrationError(
                f"Ticket API request failed: {type(exc).__name__}",
                retryable=True,
            ) from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise TicketIntegrationError(
                f"Ticket API returned HTTP {response.status_code}",
                retryable=True,
            )
        if response.status_code == 409:
            existing = self.get_sync_result(
                external_ticket_id=payload.external_ticket_id,
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                return existing
            raise TicketIntegrationError(
                "Ticket API idempotency conflict has no matching result",
                retryable=False,
            )
        if not response.is_success:
            raise TicketIntegrationError(
                f"Ticket API returned HTTP {response.status_code}",
                retryable=False,
            )
        external_request_id = response.headers.get("X-Request-ID", "")
        if not external_request_id:
            try:
                body = response.json()
            except ValueError:
                body = {}
            if isinstance(body, dict):
                external_request_id = str(
                    body.get("request_id") or body.get("id") or ""
                )
        return TicketSyncResult(
            external_request_id=external_request_id or response.headers.get(
                "Idempotency-Key",
                idempotency_key,
            )
        )

    def get_sync_result(
        self,
        *,
        external_ticket_id: str,
        idempotency_key: str,
    ) -> TicketSyncResult | None:
        if not self.settings.ticket_api_base_url:
            raise TicketIntegrationError(
                "TICKET_API_BASE_URL is not configured",
                retryable=False,
            )
        headers: dict[str, str] = {}
        if self.settings.ticket_api_key:
            headers["Authorization"] = f"Bearer {self.settings.ticket_api_key}"
        try:
            response = self._client.get(
                (
                    f"{self.settings.ticket_api_base_url.rstrip('/')}/tickets/"
                    f"{quote(external_ticket_id, safe='')}/sync-results/"
                    f"{quote(idempotency_key, safe='')}"
                ),
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise TicketIntegrationError(
                f"Ticket API result lookup failed: {type(exc).__name__}",
                retryable=True,
            ) from exc
        if response.status_code == 404:
            return None
        if response.status_code == 429 or response.status_code >= 500:
            raise TicketIntegrationError(
                f"Ticket API result lookup returned HTTP {response.status_code}",
                retryable=True,
            )
        if not response.is_success:
            raise TicketIntegrationError(
                f"Ticket API result lookup returned HTTP {response.status_code}",
                retryable=False,
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise TicketIntegrationError(
                "Ticket API result lookup returned invalid JSON",
                retryable=False,
            ) from exc
        if not isinstance(body, dict):
            raise TicketIntegrationError(
                "Ticket API result lookup returned invalid payload",
                retryable=False,
            )
        request_id = str(body.get("request_id") or body.get("id") or "")
        if not request_id:
            raise TicketIntegrationError(
                "Ticket API result lookup has no request ID",
                retryable=False,
            )
        return TicketSyncResult(external_request_id=request_id)


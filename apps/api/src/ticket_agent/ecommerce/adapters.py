from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote
from uuid import UUID

import httpx

from ticket_agent.shared.settings import Settings, get_settings


class EcommerceChannelError(Exception):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class EcommerceListingPayload:
    task_id: UUID
    sku: str
    channel: str
    product_name: str
    category: str
    price: float
    attributes: dict[str, object]
    content: dict[str, object]
    asset_ids: list[str]


@dataclass(frozen=True)
class EcommercePublishResult:
    external_listing_id: str


class EcommerceChannelAdapter(Protocol):
    @property
    def name(self) -> str: ...

    def publish(self, payload: EcommerceListingPayload) -> EcommercePublishResult: ...


class LocalEcommerceChannelAdapter:
    @property
    def name(self) -> str:
        return "local_shop"

    def publish(self, payload: EcommerceListingPayload) -> EcommercePublishResult:
        return EcommercePublishResult(
            external_listing_id=f"LOCAL-{payload.task_id.hex[:12].upper()}"
        )


class HTTPJSONEcommerceChannelAdapter:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        if not settings.ecommerce_channel_base_url:
            raise EcommerceChannelError(
                "ECOMMERCE_CHANNEL_BASE_URL is not configured",
                retryable=False,
            )
        self.settings = settings
        self._client = client or httpx.Client(
            timeout=settings.ecommerce_channel_timeout_seconds
        )

    @property
    def name(self) -> str:
        return "http_json"

    def publish(self, payload: EcommerceListingPayload) -> EcommercePublishResult:
        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": f"ecommerce-listing:{payload.task_id}",
        }
        if self.settings.ecommerce_channel_api_key:
            headers["Authorization"] = (
                f"Bearer {self.settings.ecommerce_channel_api_key}"
            )
        try:
            response = self._client.put(
                (
                    f"{self.settings.ecommerce_channel_base_url.rstrip('/')}"
                    f"/channels/{quote(payload.channel, safe='')}/listings/"
                    f"{quote(payload.sku, safe='')}"
                ),
                headers=headers,
                json={
                    "task_id": str(payload.task_id),
                    "sku": payload.sku,
                    "channel": payload.channel,
                    "product": {
                        "name": payload.product_name,
                        "category": payload.category,
                        "price": payload.price,
                        "attributes": payload.attributes,
                    },
                    "content": payload.content,
                    "asset_ids": payload.asset_ids,
                },
            )
        except httpx.HTTPError as exc:
            raise EcommerceChannelError(
                f"Ecommerce channel request failed: {type(exc).__name__}",
                retryable=True,
            ) from exc
        if not response.is_success:
            retryable = (
                response.status_code in {408, 429}
                or response.status_code >= 500
            )
            raise EcommerceChannelError(
                f"Ecommerce channel returned HTTP {response.status_code}",
                retryable=retryable,
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise EcommerceChannelError(
                "Ecommerce channel response is not valid JSON",
                retryable=True,
            ) from exc
        external_id = (
            str(body.get("listing_id") or body.get("id") or "")
            if isinstance(body, dict)
            else ""
        )
        if not external_id:
            external_id = response.headers.get(
                "Idempotency-Key",
                f"HTTP-{payload.task_id.hex[:12].upper()}",
            )
        return EcommercePublishResult(external_listing_id=external_id[:128])


def get_ecommerce_channel_adapter(
    settings: Settings | None = None,
) -> EcommerceChannelAdapter:
    resolved = settings or get_settings()
    if resolved.ecommerce_channel_provider == "http_json":
        return HTTPJSONEcommerceChannelAdapter(resolved)
    return LocalEcommerceChannelAdapter()

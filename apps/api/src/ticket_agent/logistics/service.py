from datetime import datetime
from typing import Any

import httpx

from ticket_agent.logistics.schemas import (
    LogisticsEventView,
    LogisticsQueryRequest,
    LogisticsStatusView,
)
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import Settings, get_settings

STATUS_LABELS = {
    "CREATED": "已下单",
    "PICKED_UP": "已揽收",
    "IN_TRANSIT": "运输中",
    "OUT_FOR_DELIVERY": "派送中",
    "DELIVERED": "已签收",
    "EXCEPTION": "物流异常",
    "RETURNED": "已退回",
}


class LogisticsQueryService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def query(self, payload: LogisticsQueryRequest) -> LogisticsStatusView:
        if self.settings.logistics_query_provider == "none":
            raise ApiProblem(
                status_code=503,
                code="LOGISTICS_PROVIDER_NOT_CONFIGURED",
                title="Logistics query provider is not configured",
                detail=(
                    "Configure LOGISTICS_QUERY_PROVIDER and "
                    "LOGISTICS_QUERY_BASE_URL to query real shipments."
                ),
            )
        if not self.settings.logistics_query_base_url:
            raise ApiProblem(
                status_code=503,
                code="LOGISTICS_PROVIDER_URL_MISSING",
                title="Logistics query URL is missing",
                detail="LOGISTICS_QUERY_BASE_URL is required.",
            )
        try:
            response = httpx.post(
                self.settings.logistics_query_base_url,
                json=payload.model_dump(exclude_none=True),
                headers=self._headers(),
                timeout=self.settings.logistics_query_timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ApiProblem(
                status_code=502,
                code="LOGISTICS_QUERY_FAILED",
                title="Logistics query failed",
                detail=f"External logistics service returned an error: {exc}",
            ) from exc
        if not isinstance(body, dict):
            raise ApiProblem(
                status_code=502,
                code="LOGISTICS_RESPONSE_INVALID",
                title="Logistics response is invalid",
                detail="The logistics service must return a JSON object.",
            )
        return self._view(body, fallback=payload)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.settings.logistics_query_api_key:
            headers["Authorization"] = (
                f"Bearer {self.settings.logistics_query_api_key}"
            )
        return headers

    def _view(
        self,
        body: dict[str, Any],
        *,
        fallback: LogisticsQueryRequest,
    ) -> LogisticsStatusView:
        raw_events = body.get("events", [])
        events = [
            LogisticsEventView(
                occurred_at=_parse_datetime(item.get("occurred_at")),
                location=_optional_text(item.get("location")),
                description=str(item.get("description") or "物流状态更新"),
            )
            for item in raw_events
            if isinstance(item, dict)
        ]
        status = str(body.get("status") or "UNKNOWN").upper()
        return LogisticsStatusView(
            order_id=str(body.get("order_id") or fallback.order_id or "") or None,
            tracking_number=(
                str(
                    body.get("tracking_number")
                    or fallback.tracking_number
                    or ""
                )
                or None
            ),
            carrier_code=(
                str(body.get("carrier_code") or fallback.carrier_code or "")
                or None
            ),
            status=status,
            status_label=str(
                body.get("status_label") or STATUS_LABELS.get(status, status)
            ),
            latest_event_at=_parse_datetime(body.get("latest_event_at")),
            events=events,
        )


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None

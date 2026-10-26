from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from ticket_agent.api.dependencies import Actor, DbSession
from ticket_agent.identity.dependencies import (
    ensure_metrics_viewer,
    resolve_business_unit,
)
from ticket_agent.integrations.metrics import SyncMetricsService
from ticket_agent.integrations.schemas import SyncMetricsResponse

router = APIRouter()


@router.get("/metrics/sync", response_model=SyncMetricsResponse)
def get_sync_metrics(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
    from_at: Annotated[datetime | None, Query()] = None,
    to_at: Annotated[datetime | None, Query()] = None,
) -> SyncMetricsResponse:
    ensure_metrics_viewer(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    payload = SyncMetricsService(db).summary(
        business_unit_id=business_unit_id,
        from_at=from_at,
        to_at=to_at,
    )
    return SyncMetricsResponse.model_validate(payload)


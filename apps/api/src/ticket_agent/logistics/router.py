from fastapi import APIRouter, Request

from ticket_agent.api.dependencies import Actor, DbSession, correlation_id
from ticket_agent.audit.service import record_audit
from ticket_agent.identity.dependencies import ensure_ticket_writer
from ticket_agent.logistics.schemas import LogisticsQueryRequest, LogisticsStatusView
from ticket_agent.logistics.service import LogisticsQueryService

router = APIRouter()


@router.post("/logistics/query", response_model=LogisticsStatusView)
def query_logistics(
    payload: LogisticsQueryRequest,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> LogisticsStatusView:
    ensure_ticket_writer(principal)
    result = LogisticsQueryService().query(payload)
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="logistics.queried",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="logistics_shipment",
        resource_id=result.tracking_number
        or result.order_id
        or "unknown",
        action="query_logistics",
        decision="EXECUTED",
        payload={
            "order_id": result.order_id,
            "tracking_number": result.tracking_number,
            "carrier_code": result.carrier_code,
            "status": result.status,
        },
    )
    db.commit()
    return result

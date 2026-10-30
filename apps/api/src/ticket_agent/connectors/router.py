from typing import Annotated, Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Header,
    Query,
    Request,
    status,
)
from pydantic import ValidationError

from ticket_agent.api.dependencies import Actor, DbSession, correlation_id
from ticket_agent.connectors.base import InboundEnvelope
from ticket_agent.connectors.inbound import (
    ingest_envelope,
    process_inbound_record,
    retry_inbound,
)
from ticket_agent.connectors.schemas import (
    ConnectorBindingReplace,
    ConnectorBindingView,
    ConnectorCreate,
    ConnectorHealthView,
    ConnectorInboundPayload,
    ConnectorInboundView,
    ConnectorMessageList,
    ConnectorOutboundView,
    ConnectorQueryRequest,
    ConnectorQueryView,
    ConnectorUpdate,
    ConnectorView,
)
from ticket_agent.connectors.service import (
    ExternalConnectorService,
    inbound_view,
    outbound_view,
    retry_outbound,
    verify_signature,
)
from ticket_agent.identity.dependencies import (
    ensure_business_unit_access,
    ensure_connector_viewer,
    ensure_connector_writer,
    resolve_business_unit,
)
from ticket_agent.shared.errors import ApiProblem

router = APIRouter()
webhook_router = APIRouter()


@router.get("/connectors", response_model=list[ConnectorView])
def list_connectors(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
    status_filter: Annotated[
        Literal["ACTIVE", "DISABLED"] | None,
        Query(alias="status"),
    ] = None,
) -> list[ConnectorView]:
    ensure_connector_viewer(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    service = ExternalConnectorService(db)
    return [
        service.view(connector)
        for connector in service.list_connectors(
            business_unit_id,
            status=status_filter,
        )
    ]


@router.post(
    "/connectors",
    response_model=ConnectorView,
    status_code=status.HTTP_201_CREATED,
)
def create_connector(
    payload: ConnectorCreate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> ConnectorView:
    ensure_connector_writer(principal)
    ensure_business_unit_access(principal, payload.business_unit_id)
    service = ExternalConnectorService(db)
    connector = service.create(
        payload,
        actor_id=principal.actor_id,
        correlation_id=correlation_id(request),
    )
    return service.view(connector)


@router.get("/connectors/{connector_id}", response_model=ConnectorView)
def get_connector(
    connector_id: UUID,
    db: DbSession,
    principal: Actor,
) -> ConnectorView:
    ensure_connector_viewer(principal)
    service = ExternalConnectorService(db)
    connector = service.get(connector_id)
    ensure_business_unit_access(principal, connector.business_unit_id)
    return service.view(connector)


@router.patch("/connectors/{connector_id}", response_model=ConnectorView)
def update_connector(
    connector_id: UUID,
    payload: ConnectorUpdate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> ConnectorView:
    ensure_connector_writer(principal)
    service = ExternalConnectorService(db)
    connector = service.get(connector_id)
    ensure_business_unit_access(principal, connector.business_unit_id)
    connector = service.update(
        connector_id,
        payload,
        actor_id=principal.actor_id,
        correlation_id=correlation_id(request),
    )
    return service.view(connector)


@router.post(
    "/connectors/{connector_id}/health",
    response_model=ConnectorHealthView,
)
def check_connector_health(
    connector_id: UUID,
    db: DbSession,
    principal: Actor,
) -> ConnectorHealthView:
    ensure_connector_writer(principal)
    service = ExternalConnectorService(db)
    connector = service.get(connector_id)
    ensure_business_unit_access(principal, connector.business_unit_id)
    return service.health(connector_id)


@router.post(
    "/connectors/{connector_id}/query",
    response_model=ConnectorQueryView,
)
def query_connector(
    connector_id: UUID,
    payload: ConnectorQueryRequest,
    db: DbSession,
    principal: Actor,
) -> ConnectorQueryView:
    ensure_connector_viewer(principal)
    service = ExternalConnectorService(db)
    connector = service.get(connector_id)
    ensure_business_unit_access(principal, connector.business_unit_id)
    return service.query(connector_id, payload.params)


@router.get(
    "/connectors/{connector_id}/bindings",
    response_model=list[ConnectorBindingView],
)
def list_connector_bindings(
    connector_id: UUID,
    db: DbSession,
    principal: Actor,
) -> list[ConnectorBindingView]:
    ensure_connector_viewer(principal)
    service = ExternalConnectorService(db)
    connector = service.get(connector_id)
    ensure_business_unit_access(principal, connector.business_unit_id)
    return service.binding_views(connector_id)


@router.put(
    "/connectors/{connector_id}/bindings",
    response_model=list[ConnectorBindingView],
)
def replace_connector_bindings(
    connector_id: UUID,
    payload: ConnectorBindingReplace,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> list[ConnectorBindingView]:
    ensure_connector_writer(principal)
    service = ExternalConnectorService(db)
    connector = service.get(connector_id)
    ensure_business_unit_access(principal, connector.business_unit_id)
    return service.replace_bindings(
        connector_id,
        payload.bindings,
        actor_id=principal.actor_id,
        correlation_id=correlation_id(request),
    )


@router.get(
    "/connectors/{connector_id}/messages",
    response_model=ConnectorMessageList,
)
def list_connector_messages(
    connector_id: UUID,
    db: DbSession,
    principal: Actor,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ConnectorMessageList:
    ensure_connector_viewer(principal)
    service = ExternalConnectorService(db)
    connector = service.get(connector_id)
    ensure_business_unit_access(principal, connector.business_unit_id)
    return ConnectorMessageList(
        inbound=service.inbound_views(connector_id, limit=limit),
        outbound=service.outbound_views(connector_id, limit=limit),
    )


@router.post(
    "/connectors/{connector_id}/inbound/{message_id}/retry",
    response_model=ConnectorInboundView,
)
def retry_inbound_message(
    connector_id: UUID,
    message_id: UUID,
    db: DbSession,
    principal: Actor,
) -> ConnectorInboundView:
    ensure_connector_writer(principal)
    service = ExternalConnectorService(db)
    connector = service.get(connector_id)
    ensure_business_unit_access(principal, connector.business_unit_id)
    row = retry_inbound(message_id, connector_id=connector_id)
    return inbound_view(row)


@router.post(
    "/connectors/{connector_id}/outbound/{message_id}/retry",
    response_model=ConnectorOutboundView,
)
def retry_outbound_message(
    connector_id: UUID,
    message_id: UUID,
    db: DbSession,
    principal: Actor,
) -> ConnectorOutboundView:
    ensure_connector_writer(principal)
    service = ExternalConnectorService(db)
    connector = service.get(connector_id)
    ensure_business_unit_access(principal, connector.business_unit_id)
    row = retry_outbound(message_id, connector_id=connector_id)
    return outbound_view(row)


@webhook_router.post(
    "/connectors/{connector_id}/inbound",
    response_model=ConnectorInboundView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def receive_connector_webhook(
    connector_id: UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    db: DbSession,
    signature: Annotated[
        str | None,
        Header(alias="X-Connector-Signature"),
    ] = None,
) -> ConnectorInboundView:
    body = await request.body()
    connector = ExternalConnectorService(db).get(connector_id)
    verify_signature(connector, body=body, signature=signature)
    try:
        payload = ConnectorInboundPayload.model_validate_json(body)
    except ValidationError as exc:
        raise ApiProblem(
            status_code=422,
            code="CONNECTOR_PAYLOAD_INVALID",
            title="Invalid connector payload",
            detail="The inbound payload does not match the connector schema.",
        ) from exc
    envelope = InboundEnvelope(
        external_message_id=payload.message_id,
        external_conversation_id=payload.thread_id,
        external_user_id=payload.user_id,
        subject=payload.subject,
        content=payload.content,
        raw={**payload.metadata, "source": "webhook"},
    )
    correlation = correlation_id(request)
    row, created = ingest_envelope(
        connector_id,
        envelope,
        correlation_id=correlation,
    )
    if created:
        background_tasks.add_task(
            process_inbound_record,
            row.id,
            correlation,
        )
    return inbound_view(row)

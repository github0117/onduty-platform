from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Header, Query, Request, Response, status

from ticket_agent.api.dependencies import Actor, DbSession, correlation_id
from ticket_agent.identity.dependencies import (
    ensure_business_unit_access,
    ensure_ticket_creator,
    ensure_ticket_sync,
    ensure_ticket_view,
    ensure_ticket_writer,
    resolve_business_unit,
)
from ticket_agent.outbox.service import dispatch_outbox_event
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import get_settings
from ticket_agent.tickets.domain import TicketStatus
from ticket_agent.tickets.schemas import (
    ClassificationOverrideRequest,
    MutationResult,
    ReviewRequest,
    SyncBatchRetryRequest,
    SyncBatchRetryResponse,
    SyncRetryRequest,
    TakeoverRequest,
    TicketAccepted,
    TicketCreate,
    TicketDetail,
    TicketList,
)
from ticket_agent.tickets.service import TicketService

router = APIRouter()


@router.post(
    "/tickets",
    response_model=TicketAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create a ticket and start digital processing",
)
def create_ticket(
    payload: TicketCreate,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    db: DbSession,
    principal: Actor,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> TicketAccepted:
    if not idempotency_key:
        raise ApiProblem(
            status_code=400,
            code="INVALID_REQUEST",
            title="Idempotency-Key is required",
            detail="All ticket creation requests must include Idempotency-Key.",
        )

    ensure_ticket_creator(principal, payload.requester.external_ref)
    ticket, created, outbox_event_id = TicketService(db).create(
        payload=payload,
        idempotency_key=idempotency_key,
        principal=principal,
        correlation_id=correlation_id(request),
    )
    if created and outbox_event_id:
        background_tasks.add_task(dispatch_outbox_event, outbox_event_id)
    response.headers["Location"] = f"/api/v1/tickets/{ticket.id}"
    return TicketAccepted(
        id=ticket.id,
        employee_id=ticket.employee_id,
        status=ticket.status,
        workflow_state=ticket.workflow_state,
        version=ticket.version,
        created_at=ticket.created_at,
    )


@router.get("/tickets", response_model=TicketList)
def list_tickets(
    db: DbSession,
    principal: Actor,
    business_unit_id: str | None = None,
    ticket_status: Annotated[str | None, Query(alias="status")] = None,
    include_closed: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> TicketList:
    if ticket_status and ticket_status not in {item.value for item in TicketStatus}:
        raise ApiProblem(
            status_code=422,
            code="SCHEMA_VALIDATION_FAILED",
            title="Invalid status filter",
            detail=f"Unknown ticket status: {ticket_status}",
        )
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    return TicketService(db).list_tickets(
        business_unit_id=business_unit_id,
        status=ticket_status,
        requester_ref=principal.customer_ref if principal.role == "requester" else None,
        include_closed=include_closed,
        limit=limit,
    )


@router.post("/tickets/test-cleanup", response_model=dict[str, int])
def cleanup_test_tickets(
    db: DbSession,
    principal: Actor,
    business_unit_id: str = Query(min_length=1),
    requester_prefix: str = Query(min_length=1, max_length=100),
) -> dict[str, int]:
    if get_settings().app_env not in {"development", "test"}:
        raise ApiProblem(
            status_code=403,
            code="TEST_CLEANUP_DISABLED",
            title="Test cleanup is disabled",
            detail="Test ticket cleanup is only available in development or test.",
        )
    if principal.role != "admin":
        raise ApiProblem(
            status_code=403,
            code="FORBIDDEN",
            title="Admin role required",
            detail="Only administrators can clean up test tickets.",
        )
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    closed = TicketService(db).archive_test_tickets(
        business_unit_id=business_unit_id,
        requester_prefix=requester_prefix,
    )
    return {"closed": closed}


@router.post(
    "/tickets/{ticket_id}/archive-test-data",
    response_model=MutationResult,
)
def archive_test_ticket(
    ticket_id: UUID,
    db: DbSession,
    principal: Actor,
) -> MutationResult:
    if get_settings().app_env not in {"development", "test"}:
        raise ApiProblem(
            status_code=403,
            code="TEST_CLEANUP_DISABLED",
            title="Test cleanup is disabled",
            detail="Test ticket cleanup is only available in development or test.",
        )
    if principal.role != "admin":
        raise ApiProblem(
            status_code=403,
            code="FORBIDDEN",
            title="Admin role required",
            detail="Only administrators can clean up test tickets.",
        )
    ticket = TicketService(db).archive_test_ticket(ticket_id, principal=principal)
    return MutationResult(
        ticket_id=ticket.id,
        version=ticket.version,
        status=ticket.status,
        workflow_state=ticket.workflow_state,
        message="测试工单已关闭并从默认队列隐藏",
    )


@router.get("/tickets/{ticket_id}", response_model=TicketDetail)
def get_ticket(ticket_id: UUID, db: DbSession, principal: Actor) -> TicketDetail:
    detail = TicketService(db).detail(ticket_id)
    ensure_business_unit_access(principal, detail.business_unit_id)
    ensure_ticket_view(principal, detail.requester.external_ref)
    return detail


@router.post("/tickets/{ticket_id}/takeover", response_model=MutationResult)
def take_over_ticket(
    ticket_id: UUID,
    payload: TakeoverRequest,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> MutationResult:
    ensure_ticket_writer(principal)
    ticket = TicketService(db).take_over(
        ticket_id=ticket_id,
        payload=payload,
        principal=principal,
        correlation_id=correlation_id(request),
    )
    return MutationResult(
        ticket_id=ticket.id,
        version=ticket.version,
        status=ticket.status,
        workflow_state=ticket.workflow_state,
        message="Ticket taken over by a human agent.",
    )


@router.post("/tickets/{ticket_id}/reviews", response_model=MutationResult)
def review_draft(
    ticket_id: UUID,
    payload: ReviewRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: DbSession,
    principal: Actor,
) -> MutationResult:
    ensure_ticket_writer(principal)
    ticket, sync_event_id = TicketService(db).review(
        ticket_id=ticket_id,
        payload=payload,
        principal=principal,
        correlation_id=correlation_id(request),
    )
    if sync_event_id:
        background_tasks.add_task(dispatch_outbox_event, sync_event_id)
    return MutationResult(
        ticket_id=ticket.id,
        version=ticket.version,
        status=ticket.status,
        workflow_state=ticket.workflow_state,
        message=(
            "Draft accepted; external synchronization queued."
            if sync_event_id
            else "Draft review recorded."
        ),
    )


@router.post(
    "/tickets/{ticket_id}/sync-attempts",
    response_model=MutationResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_external_sync(
    ticket_id: UUID,
    payload: SyncRetryRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: DbSession,
    principal: Actor,
) -> MutationResult:
    ensure_ticket_writer(principal)
    ticket, event_id = TicketService(db).request_sync_retry(
        ticket_id=ticket_id,
        payload=payload,
        principal=principal,
        correlation_id=correlation_id(request),
    )
    background_tasks.add_task(dispatch_outbox_event, event_id)
    return MutationResult(
        ticket_id=ticket.id,
        version=ticket.version,
        status=ticket.status,
        workflow_state=ticket.workflow_state,
        message="External synchronization retry queued.",
    )


@router.post(
    "/tickets/sync-attempts:batch",
    response_model=SyncBatchRetryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_external_sync_batch(
    payload: SyncBatchRetryRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: DbSession,
    principal: Actor,
) -> SyncBatchRetryResponse:
    ensure_ticket_sync(principal)
    items, event_ids = TicketService(db).batch_request_sync_retry(
        payload=payload,
        principal=principal,
        correlation_id=correlation_id(request),
    )
    for event_id in event_ids:
        background_tasks.add_task(dispatch_outbox_event, event_id)
    return SyncBatchRetryResponse(items=items)


@router.post(
    "/tickets/{ticket_id}/classification-overrides",
    response_model=MutationResult,
)
def override_classification(
    ticket_id: UUID,
    payload: ClassificationOverrideRequest,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> MutationResult:
    ensure_ticket_writer(principal)
    ticket = TicketService(db).override_classification(
        ticket_id=ticket_id,
        payload=payload,
        principal=principal,
        correlation_id=correlation_id(request),
    )
    return MutationResult(
        ticket_id=ticket.id,
        version=ticket.version,
        status=ticket.status,
        workflow_state=ticket.workflow_state,
        message="Classification override recorded.",
    )


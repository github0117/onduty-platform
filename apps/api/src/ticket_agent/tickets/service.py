import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ticket_agent.audit.service import record_audit
from ticket_agent.business_entries.service import service_entry_employee_ids
from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.digital_employees.router_service import DigitalEmployeeRouter
from ticket_agent.digital_employees.service import DigitalEmployeeService
from ticket_agent.identity.dependencies import ensure_business_unit_access
from ticket_agent.identity.models import Principal
from ticket_agent.knowledge.models import KnowledgeFeedback, KnowledgeRepairTask
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.tickets.domain import TicketStatus, WorkflowState
from ticket_agent.tickets.models import (
    AnswerDraft,
    OutboxEvent,
    Ticket,
    TicketAnalysis,
    WorkflowTransition,
)
from ticket_agent.tickets.schemas import (
    ClassificationOverrideRequest,
    ClassificationView,
    DigitalEmployeeReference,
    DraftView,
    PriorityView,
    RequesterInput,
    ReviewRequest,
    RiskView,
    RoutingView,
    SourceInput,
    SyncBatchItem,
    SyncBatchRetryRequest,
    SyncRetryRequest,
    SyncView,
    TakeoverRequest,
    TicketCreate,
    TicketDetail,
    TicketList,
    TicketListItem,
)


class TicketService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        payload: TicketCreate,
        idempotency_key: str,
        principal: Principal,
        correlation_id: str,
        enqueue: bool = True,
        commit: bool = True,
    ) -> tuple[Ticket, bool, UUID | None]:
        """Create a ticket, or return the one an earlier request created.

        ``commit`` lets a caller that must keep the surrounding row locks (the
        conversation runtime does) leave the commit to its own transaction.
        """
        ensure_business_unit_access(principal, payload.business_unit_id)
        request_hash = self._request_hash(payload)
        existing = self.session.scalar(
            select(Ticket).where(Ticket.idempotency_key == idempotency_key)
        )
        if existing is not None:
            ensure_business_unit_access(principal, existing.business_unit_id)
            return self._validate_replay(existing, request_hash), False, None

        employee_service = DigitalEmployeeService(self.session)
        route_decision = None
        if payload.employee_id is None:
            allowed_employee_ids = self._service_entry_employee_ids(
                payload.metadata.get("service_entry_id"),
                business_unit_id=payload.business_unit_id,
            )
            try:
                route_result = DigitalEmployeeRouter(
                    self.session
                ).route_text(
                    business_unit_id=payload.business_unit_id,
                    subject=payload.subject,
                    body=payload.body,
                    channel=payload.source.channel,
                    allowed_employee_ids=allowed_employee_ids,
                )
            except ValueError as exc:
                raise ApiProblem(
                    status_code=409,
                    code="BUSINESS_SERVICE_ENTRY_NO_EMPLOYEE",
                    title="业务入口没有可用员工",
                    detail="请为当前业务入口绑定至少一个已启用的数字员工。",
                ) from exc
            employee = route_result.employee
            route_decision = route_result.decision
        else:
            employee = employee_service.get(payload.employee_id)
            if employee.status != "ACTIVE":
                raise ApiProblem(
                    status_code=409,
                    code="DIGITAL_EMPLOYEE_DISABLED",
                    title="Digital employee is disabled",
                    detail="Tickets cannot be created for a disabled digital employee.",
                )
            if employee.business_unit_id != payload.business_unit_id:
                raise ApiProblem(
                    status_code=422,
                    code="DIGITAL_EMPLOYEE_SCOPE_MISMATCH",
                    title="Digital employee scope mismatch",
                    detail="The digital employee does not belong to this business unit.",
                )

        ticket = Ticket(
            employee_id=employee.id,
            business_unit_id=payload.business_unit_id,
            source_system=payload.source.system,
            source_ticket_id=payload.source.external_ticket_id,
            source_channel=payload.source.channel,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            requester_ref=payload.requester.external_ref,
            customer_tier=payload.requester.customer_tier,
            subject=payload.subject,
            body=payload.body,
            status=TicketStatus.OPEN,
            workflow_state=WorkflowState.RECEIVED,
            external_metadata={
                "locale": payload.locale,
                "attachments": [item.model_dump(mode="json") for item in payload.attachments],
                **payload.metadata,
            },
        )
        self.session.add(ticket)
        try:
            self.session.flush()
            if route_decision is not None:
                route_decision.ticket_id = ticket.id
        except IntegrityError as exc:
            self.session.rollback()
            existing = self.session.scalar(
                select(Ticket).where(
                    (Ticket.idempotency_key == idempotency_key)
                    | (
                        (Ticket.source_system == payload.source.system)
                        & (Ticket.source_ticket_id == payload.source.external_ticket_id)
                    )
                )
            )
            if existing is None:
                raise exc
            return self._validate_replay(existing, request_hash), False, None

        outbox_event_id: UUID | None = None
        if enqueue:
            outbox_event = OutboxEvent(
                aggregate_type="ticket",
                aggregate_id=ticket.id,
                event_type="ticket.received",
                payload_json={
                    "ticket_id": str(ticket.id),
                    "correlation_id": correlation_id,
                },
            )
            self.session.add(outbox_event)
            self.session.flush()
            outbox_event_id = outbox_event.id
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="ticket.received",
            actor_type="USER",
            actor_id=principal.actor_id,
            on_behalf_of=principal.actor_id,
            resource_id=ticket.id,
            action="create",
            decision="EXECUTED",
            payload={
                "source_system": ticket.source_system,
                "source_ticket_id": ticket.source_ticket_id,
                "business_unit_id": ticket.business_unit_id,
                "employee_key": employee.employee_key,
            },
        )
        if commit:
            self.session.commit()
            self.session.refresh(ticket)
        return ticket, True, outbox_event_id

    def _service_entry_employee_ids(
        self,
        raw_entry_id: object,
        *,
        business_unit_id: str,
    ) -> set[UUID] | None:
        return service_entry_employee_ids(
            self.session,
            raw_entry_id,
            business_unit_id=business_unit_id,
        )

    def list_tickets(
        self,
        *,
        business_unit_id: str,
        status: str | None,
        requester_ref: str | None,
        include_closed: bool,
        limit: int,
    ) -> TicketList:
        filters = [Ticket.business_unit_id == business_unit_id]
        if status:
            filters.append(Ticket.status == status)
        if requester_ref:
            filters.append(Ticket.requester_ref == requester_ref)
        if not include_closed:
            filters.append(Ticket.status != TicketStatus.CLOSED)

        total = self.session.scalar(select(func.count()).select_from(Ticket).where(*filters)) or 0
        tickets = self.session.scalars(
            select(Ticket)
            .where(*filters)
            .order_by(Ticket.created_at.desc())
            .limit(limit)
        ).all()
        return TicketList(
            items=[
                TicketListItem(
                    id=ticket.id,
                    subject=ticket.subject,
                    status=ticket.status,
                    workflow_state=ticket.workflow_state,
                    category_primary=ticket.category_primary,
                    priority=ticket.priority,
                    risk_level=ticket.risk_level,
                    queue_id=ticket.queue_id,
                    needs_human=ticket.needs_human,
                    version=ticket.version,
                    created_at=ticket.created_at,
                    updated_at=ticket.updated_at,
                )
                for ticket in tickets
            ],
            total=total,
        )

    def archive_test_ticket(self, ticket_id: UUID, *, principal: Principal) -> Ticket:
        ticket = self.get(ticket_id)
        ensure_business_unit_access(principal, ticket.business_unit_id)
        ticket.status = TicketStatus.CLOSED
        ticket.workflow_state = WorkflowState.COMPLETED
        ticket.needs_human = False
        ticket.version += 1
        self.session.commit()
        self.session.refresh(ticket)
        return ticket

    def archive_test_tickets(
        self,
        *,
        business_unit_id: str,
        requester_prefix: str,
    ) -> int:
        tickets = list(
            self.session.scalars(
                select(Ticket).where(
                    Ticket.business_unit_id == business_unit_id,
                    Ticket.requester_ref.like(f"{requester_prefix}%"),
                    Ticket.status != TicketStatus.CLOSED,
                )
            ).all()
        )
        for ticket in tickets:
            ticket.status = TicketStatus.CLOSED
            ticket.workflow_state = WorkflowState.COMPLETED
            ticket.needs_human = False
            ticket.version += 1
        self.session.commit()
        return len(tickets)

    def get(self, ticket_id: UUID) -> Ticket:
        ticket = self.session.get(Ticket, ticket_id)
        if ticket is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Ticket not found",
                detail=f"Ticket {ticket_id} does not exist.",
            )
        return ticket

    def detail(self, ticket_id: UUID) -> TicketDetail:
        ticket = self.get(ticket_id)
        employee = self._employee_for_ticket(ticket)
        analysis = self.session.scalar(
            select(TicketAnalysis)
            .where(TicketAnalysis.ticket_id == ticket.id)
            .order_by(TicketAnalysis.created_at.desc())
            .limit(1)
        )
        draft = self.session.scalar(
            select(AnswerDraft)
            .where(AnswerDraft.ticket_id == ticket.id)
            .order_by(AnswerDraft.created_at.desc())
            .limit(1)
        )
        analysis_json = analysis.result_json if analysis else {}
        priority_reasons = analysis_json.get("reason_codes", []) if analysis_json else []
        risk_reasons = analysis_json.get("reason_codes", []) if analysis_json else []
        risk_tags = analysis_json.get("risk_tags", []) if analysis_json else []

        return TicketDetail(
            id=ticket.id,
            business_unit_id=ticket.business_unit_id,
            employee=DigitalEmployeeReference(
                id=employee.id,
                employee_key=employee.employee_key,
                name=employee.name,
                version=employee.version,
                workflow_key=employee.workflow_key,
            ),
            source=SourceInput(
                system=ticket.source_system,
                channel=ticket.source_channel,
                external_ticket_id=ticket.source_ticket_id,
            ),
            requester=RequesterInput(
                external_ref=ticket.requester_ref,
                customer_tier=ticket.customer_tier,
            ),
            subject=ticket.subject,
            body=ticket.body,
            summary=ticket.summary,
            status=ticket.status,
            workflow_state=ticket.workflow_state,
            classification=(
                ClassificationView(
                    primary=ticket.category_primary,
                    secondary=ticket.category_secondary or "unknown",
                    confidence=ticket.confidence or 0,
                )
                if ticket.category_primary
                else None
            ),
            priority=(
                PriorityView(level=ticket.priority, reason_codes=priority_reasons)
                if ticket.priority
                else None
            ),
            risk=(
                RiskView(
                    level=ticket.risk_level,
                    tags=risk_tags,
                    reason_codes=risk_reasons,
                )
                if ticket.risk_level
                else None
            ),
            routing=RoutingView(
                queue_id=ticket.queue_id,
                needs_human=ticket.needs_human,
                human_reason=ticket.human_reason,
            ),
            needs_human=ticket.needs_human,
            sync=SyncView(
                status=ticket.sync_status,
                attempts=ticket.sync_attempts,
                error=ticket.sync_error,
                external_request_id=ticket.external_request_id,
                synced_at=ticket.external_synced_at,
            ),
            draft=(
                DraftView(
                    id=draft.id,
                    text=draft.text,
                    status=draft.status,
                    generator_provider=draft.generator_provider,
                    generator_model=draft.generator_model,
                    grounding_status=draft.grounding_status,
                    citations=draft.citations_json,
                    claims=draft.claims_json or [],
                    created_at=draft.created_at,
                    reviewed_at=draft.reviewed_at,
                )
                if draft
                else None
            ),
            version=ticket.version,
            created_at=ticket.created_at,
            updated_at=ticket.updated_at,
            allowed_actions=self._allowed_actions(ticket),
        )

    def take_over(
        self,
        *,
        ticket_id: UUID,
        payload: TakeoverRequest,
        principal: Principal,
        correlation_id: str,
    ) -> Ticket:
        ticket = self._locked_ticket(ticket_id, principal=principal)
        if ticket.workflow_state == WorkflowState.TAKEN_OVER:
            return ticket
        self._require_version(ticket, payload.expected_version)
        if ticket.workflow_state in {WorkflowState.COMPLETED, WorkflowState.FAILED_TERMINAL}:
            self._invalid_state(ticket, WorkflowState.TAKEN_OVER)

        previous = ticket.workflow_state
        ticket.workflow_state = WorkflowState.TAKEN_OVER
        ticket.status = TicketStatus.IN_PROGRESS
        ticket.needs_human = True
        ticket.human_reason = payload.reason_code
        ticket.version += 1
        self.session.add(
            WorkflowTransition(
                ticket_id=ticket.id,
                from_state=previous,
                to_state=WorkflowState.TAKEN_OVER,
                reason_code=payload.reason_code,
                actor_type="USER",
                actor_id=principal.actor_id,
            )
        )
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="ticket.taken_over",
            actor_type="USER",
            actor_id=principal.actor_id,
            resource_id=ticket.id,
            action="takeover",
            decision="EXECUTED",
            reason_code=payload.reason_code,
            payload={"note": payload.note} if payload.note else {},
        )
        self.session.commit()
        self.session.refresh(ticket)
        return ticket

    def _employee_for_ticket(self, ticket: Ticket) -> DigitalEmployee:
        if ticket.employee_id is not None:
            employee = self.session.get(DigitalEmployee, ticket.employee_id)
            if employee is not None:
                return employee
        return DigitalEmployeeService(self.session).ensure_default(ticket.business_unit_id)

    def review(
        self,
        *,
        ticket_id: UUID,
        payload: ReviewRequest,
        principal: Principal,
        correlation_id: str,
    ) -> tuple[Ticket, UUID | None]:
        ticket = self._locked_ticket(ticket_id, principal=principal)
        self._require_version(ticket, payload.expected_version)
        if ticket.workflow_state != WorkflowState.PENDING_REVIEW:
            self._invalid_state(ticket, WorkflowState.PENDING_REVIEW)

        draft = self.session.scalar(
            select(AnswerDraft)
            .where(AnswerDraft.ticket_id == ticket.id)
            .order_by(AnswerDraft.created_at.desc())
            .limit(1)
        )
        if draft is None:
            raise ApiProblem(
                status_code=409,
                code="DRAFT_NOT_FOUND",
                title="Draft is not available",
                detail="The ticket has no draft to review.",
            )

        original_draft_text = draft.text
        edited = False
        if payload.decision == "EDITED_AND_ACCEPTED":
            if not payload.edited_text or not payload.edited_text.strip():
                raise ApiProblem(
                    status_code=422,
                    code="SCHEMA_VALIDATION_FAILED",
                    title="Edited text is required",
                    detail="edited_text is required for EDITED_AND_ACCEPTED.",
                )
            edited_text = payload.edited_text.strip()
            edited = edited_text != original_draft_text
            draft.text = edited_text

        draft.status = payload.decision
        draft.reviewed_at = datetime.now(UTC)
        previous = ticket.workflow_state
        sync_event_id: UUID | None = None
        if payload.decision in {"ACCEPTED", "EDITED_AND_ACCEPTED"}:
            ticket.workflow_state = WorkflowState.SYNCING
            ticket.status = TicketStatus.IN_PROGRESS
            ticket.sync_status = "PENDING"
            ticket.sync_attempts = 0
            ticket.sync_error = None
            sync_event = OutboxEvent(
                aggregate_type="ticket",
                aggregate_id=ticket.id,
                event_type="ticket.sync_external",
                payload_json={
                    "ticket_id": str(ticket.id),
                    "correlation_id": correlation_id,
                },
            )
            self.session.add(sync_event)
            self.session.flush()
            sync_event_id = sync_event.id
        elif payload.decision == "ESCALATED":
            ticket.workflow_state = WorkflowState.NEEDS_HUMAN
            ticket.status = TicketStatus.WAITING_HUMAN
            ticket.needs_human = True
            ticket.human_reason = payload.reason_code
        else:
            ticket.workflow_state = WorkflowState.NEEDS_HUMAN
            ticket.status = TicketStatus.WAITING_HUMAN
            ticket.needs_human = True
            ticket.human_reason = payload.reason_code

        ticket.version += 1
        self.session.add(
            WorkflowTransition(
                ticket_id=ticket.id,
                from_state=previous,
                to_state=ticket.workflow_state,
                reason_code=payload.reason_code,
                actor_type="USER",
                actor_id=principal.actor_id,
            )
        )
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="draft.reviewed",
            actor_type="USER",
            actor_id=principal.actor_id,
            resource_id=ticket.id,
            action="review",
            decision="EXECUTED",
            reason_code=payload.reason_code,
            payload={
                "draft_id": str(draft.id),
                "review_decision": payload.decision,
                "sync_requested": sync_event_id is not None,
            },
        )
        self.session.commit()
        if edited or payload.decision in {"REJECTED", "ESCALATED"}:
            self._record_human_edit_feedback(
                ticket=ticket,
                draft=draft,
                original_draft_text=original_draft_text,
                actor_id=principal.actor_id,
                reason_code=(
                    "HUMAN_EDITED"
                    if edited
                    else f"AGENT_{payload.decision}"
                ),
                details=(
                    f"人工最终回复：{draft.text}"
                    if edited
                    else f"审核动作：{payload.decision}；原因：{payload.reason_code}"
                ),
            )
        if payload.decision in {"ACCEPTED", "EDITED_AND_ACCEPTED"}:
            from ticket_agent.customer_service.service import CustomerConversationService

            CustomerConversationService(
                self.session
            ).append_assistant_reply(ticket.id, draft.text)
        self.session.refresh(ticket)
        return ticket, sync_event_id

    def _record_human_edit_feedback(
        self,
        *,
        ticket: Ticket,
        draft: AnswerDraft,
        original_draft_text: str,
        actor_id: str,
        reason_code: str,
        details: str,
    ) -> None:
        citation = next(
            (
                item
                for item in draft.citations_json
                if isinstance(item, dict)
            ),
            {},
        )
        raw_space_id = citation.get("space_id")
        space_id = UUID(str(raw_space_id)) if raw_space_id else None
        repair = KnowledgeRepairTask(
            business_unit_id=ticket.business_unit_id,
            knowledge_space_id=space_id,
            status="OPEN",
            priority="P2",
            title=f"人工改写：{ticket.subject}"[:300],
            query=f"{ticket.subject}\n{ticket.body}",
            expected_titles_json=[],
            returned_titles_json=[],
            created_by=actor_id,
        )
        self.session.add(repair)
        self.session.flush()
        self.session.add(
            KnowledgeFeedback(
                business_unit_id=ticket.business_unit_id,
                knowledge_space_id=space_id,
                employee_id=ticket.employee_id,
                ticket_id=ticket.id,
                query=f"{ticket.subject}\n{ticket.body}",
                answer=original_draft_text,
                rating="NEGATIVE",
                reason_code=reason_code,
                details=details,
                repair_task_id=repair.id,
                created_by=actor_id,
            )
        )
        self.session.commit()

    def override_classification(
        self,
        *,
        ticket_id: UUID,
        payload: ClassificationOverrideRequest,
        principal: Principal,
        correlation_id: str,
    ) -> Ticket:
        ticket = self._locked_ticket(ticket_id, principal=principal)
        self._require_version(ticket, payload.expected_version)
        if ticket.workflow_state in {WorkflowState.TAKEN_OVER, WorkflowState.COMPLETED}:
            self._invalid_state(ticket, WorkflowState.NEEDS_HUMAN)
        previous = ticket.workflow_state
        before = {
            "primary": ticket.category_primary,
            "secondary": ticket.category_secondary,
        }
        ticket.category_primary = payload.primary
        ticket.category_secondary = payload.secondary
        ticket.needs_human = True
        ticket.human_reason = "MANUAL_CLASSIFICATION_OVERRIDE"
        ticket.status = TicketStatus.WAITING_HUMAN
        ticket.workflow_state = WorkflowState.NEEDS_HUMAN
        ticket.version += 1
        self.session.add(
            WorkflowTransition(
                ticket_id=ticket.id,
                from_state=previous,
                to_state=WorkflowState.NEEDS_HUMAN,
                reason_code=payload.reason_code,
                actor_type="USER",
                actor_id=principal.actor_id,
            )
        )
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="classification.overridden",
            actor_type="USER",
            actor_id=principal.actor_id,
            resource_id=ticket.id,
            action="override_classification",
            decision="EXECUTED",
            reason_code=payload.reason_code,
            payload={
                "before": before,
                "after": {"primary": payload.primary, "secondary": payload.secondary},
                "note": payload.note,
            },
        )
        self.session.commit()
        self.session.refresh(ticket)
        return ticket

    def request_sync_retry(
        self,
        *,
        ticket_id: UUID,
        payload: SyncRetryRequest,
        principal: Principal,
        correlation_id: str,
    ) -> tuple[Ticket, UUID]:
        ticket = self._locked_ticket(ticket_id, principal=principal)
        self._require_version(ticket, payload.expected_version)
        if ticket.sync_status == "SUCCEEDED":
            raise ApiProblem(
                status_code=409,
                code="SYNC_ALREADY_SUCCEEDED",
                title="Ticket already synchronized",
                detail="The ticket was already synchronized successfully.",
            )
        if ticket.workflow_state in {WorkflowState.TAKEN_OVER, WorkflowState.COMPLETED}:
            self._invalid_state(ticket, WorkflowState.SYNCING)
        previous_state = ticket.workflow_state
        ticket.workflow_state = WorkflowState.SYNCING
        ticket.status = TicketStatus.IN_PROGRESS
        ticket.sync_status = "PENDING"
        ticket.sync_attempts = 0
        ticket.sync_error = None
        ticket.needs_human = False
        ticket.human_reason = None
        ticket.version += 1
        if previous_state != WorkflowState.SYNCING:
            self.session.add(
                WorkflowTransition(
                    ticket_id=ticket.id,
                    from_state=previous_state,
                    to_state=WorkflowState.SYNCING,
                    reason_code=payload.reason_code,
                    actor_type="USER",
                    actor_id=principal.actor_id,
                )
            )
        event = OutboxEvent(
            aggregate_type="ticket",
            aggregate_id=ticket.id,
            event_type="ticket.sync_external",
            payload_json={
                "ticket_id": str(ticket.id),
                "correlation_id": correlation_id,
            },
        )
        self.session.add(event)
        self.session.flush()
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="ticket.sync_retry_requested",
            actor_type="USER",
            actor_id=principal.actor_id,
            resource_id=ticket.id,
            action="retry_sync",
            decision="EXECUTED",
            reason_code=payload.reason_code,
        )
        self.session.commit()
        self.session.refresh(ticket)
        return ticket, event.id

    def batch_request_sync_retry(
        self,
        *,
        payload: SyncBatchRetryRequest,
        principal: Principal,
        correlation_id: str,
    ) -> tuple[list[SyncBatchItem], list[UUID]]:
        items: list[SyncBatchItem] = []
        event_ids: list[UUID] = []
        seen: set[UUID] = set()
        if payload.ticket_ids:
            ticket_units = self.session.execute(
                select(Ticket.id, Ticket.business_unit_id).where(
                    Ticket.id.in_(list(set(payload.ticket_ids)))
                )
            ).all()
            for _ticket_id, business_unit_id in ticket_units:
                ensure_business_unit_access(principal, business_unit_id)
        for ticket_id in payload.ticket_ids:
            if ticket_id in seen:
                items.append(
                    SyncBatchItem(
                        ticket_id=ticket_id,
                        accepted=False,
                        code="DUPLICATE",
                    )
                )
                continue
            seen.add(ticket_id)
            ticket = self.session.scalar(
                select(Ticket).where(Ticket.id == ticket_id).with_for_update()
            )
            if ticket is None:
                items.append(
                    SyncBatchItem(
                        ticket_id=ticket_id,
                        accepted=False,
                        code="NOT_FOUND",
                    )
                )
                continue
            if ticket.sync_status == "SUCCEEDED":
                items.append(
                    SyncBatchItem(
                        ticket_id=ticket.id,
                        accepted=False,
                        code="ALREADY_SUCCEEDED",
                        version=ticket.version,
                        workflow_state=ticket.workflow_state,
                        sync_status=ticket.sync_status,
                    )
                )
                continue
            if ticket.workflow_state in {WorkflowState.TAKEN_OVER, WorkflowState.COMPLETED}:
                items.append(
                    SyncBatchItem(
                        ticket_id=ticket.id,
                        accepted=False,
                        code="INVALID_STATE",
                        version=ticket.version,
                        workflow_state=ticket.workflow_state,
                        sync_status=ticket.sync_status,
                    )
                )
                continue
            if ticket.workflow_state not in {
                WorkflowState.SYNCING,
                WorkflowState.NEEDS_HUMAN,
            }:
                items.append(
                    SyncBatchItem(
                        ticket_id=ticket.id,
                        accepted=False,
                        code="NOT_SYNC_CANDIDATE",
                        version=ticket.version,
                        workflow_state=ticket.workflow_state,
                        sync_status=ticket.sync_status,
                    )
                )
                continue

            previous_state = ticket.workflow_state
            ticket.workflow_state = WorkflowState.SYNCING
            ticket.status = TicketStatus.IN_PROGRESS
            ticket.sync_status = "PENDING"
            ticket.sync_attempts = 0
            ticket.sync_error = None
            ticket.needs_human = False
            ticket.human_reason = None
            ticket.version += 1
            if previous_state != WorkflowState.SYNCING:
                self.session.add(
                    WorkflowTransition(
                        ticket_id=ticket.id,
                        from_state=previous_state,
                        to_state=WorkflowState.SYNCING,
                        reason_code=payload.reason_code,
                        actor_type="USER",
                        actor_id=principal.actor_id,
                    )
                )
            event = OutboxEvent(
                aggregate_type="ticket",
                aggregate_id=ticket.id,
                event_type="ticket.sync_external",
                payload_json={
                    "ticket_id": str(ticket.id),
                    "correlation_id": correlation_id,
                },
            )
            self.session.add(event)
            record_audit(
                self.session,
                correlation_id=correlation_id,
                event_type="ticket.sync_retry_requested",
                actor_type="USER",
                actor_id=principal.actor_id,
                resource_id=ticket.id,
                action="retry_sync_batch",
                decision="EXECUTED",
                reason_code=payload.reason_code,
            )
            self.session.commit()
            event_ids.append(event.id)
            items.append(
                SyncBatchItem(
                    ticket_id=ticket.id,
                    accepted=True,
                    code="QUEUED",
                    version=ticket.version,
                    workflow_state=ticket.workflow_state,
                    sync_status=ticket.sync_status,
                )
            )
        return items, event_ids

    def _locked_ticket(self, ticket_id: UUID, *, principal: Principal) -> Ticket:
        ticket = self.session.scalar(
            select(Ticket).where(Ticket.id == ticket_id).with_for_update()
        )
        if ticket is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Ticket not found",
                detail=f"Ticket {ticket_id} does not exist.",
            )
        ensure_business_unit_access(principal, ticket.business_unit_id)
        return ticket

    @staticmethod
    def _allowed_actions(ticket: Ticket) -> list[str]:
        actions = ["VIEW_AUDIT"]
        if ticket.workflow_state == WorkflowState.PENDING_REVIEW:
            actions.extend(["REVIEW_DRAFT", "TAKEOVER", "OVERRIDE_CLASSIFICATION"])
        elif ticket.workflow_state == WorkflowState.NEEDS_HUMAN:
            actions.extend(["TAKEOVER", "OVERRIDE_CLASSIFICATION"])
        elif ticket.workflow_state == WorkflowState.TAKEN_OVER:
            actions.append("CONTINUE_HUMAN_WORK")
        return actions

    @staticmethod
    def _request_hash(payload: TicketCreate) -> str:
        serialized = json.dumps(payload.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_replay(ticket: Ticket, request_hash: str) -> Ticket:
        if ticket.request_hash != request_hash:
            raise ApiProblem(
                status_code=409,
                code="IDEMPOTENCY_CONFLICT",
                title="Idempotency key conflict",
                detail="The idempotency key was already used with a different request body.",
                context={"ticket_id": str(ticket.id)},
            )
        return ticket

    @staticmethod
    def _require_version(ticket: Ticket, expected_version: int) -> None:
        if ticket.version != expected_version:
            raise ApiProblem(
                status_code=409,
                code="VERSION_CONFLICT",
                title="Version conflict",
                detail="The ticket changed since it was loaded.",
                retryable=True,
                context={
                    "expected_version": expected_version,
                    "actual_version": ticket.version,
                },
            )

    @staticmethod
    def _invalid_state(ticket: Ticket, expected: str) -> None:
        raise ApiProblem(
            status_code=409,
            code="INVALID_STATE_TRANSITION",
            title="Invalid state transition",
            detail=f"Ticket is in {ticket.workflow_state}, expected {expected}.",
            context={"ticket_id": str(ticket.id)},
        )


def analysis_payload_for_test(session: Session, ticket_id: UUID) -> dict[str, Any]:
    analysis = session.scalar(
        select(TicketAnalysis)
        .where(TicketAnalysis.ticket_id == ticket_id)
        .order_by(TicketAnalysis.created_at.desc())
        .limit(1)
    )
    return analysis.result_json if analysis else {}


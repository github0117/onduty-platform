from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ticket_agent.audit.service import record_audit
from ticket_agent.digital_employees.service import DigitalEmployeeService
from ticket_agent.knowledge.embedding_factory import get_embedding_provider
from ticket_agent.knowledge.service import KnowledgeService
from ticket_agent.model_gateway.profile import build_reranker_for_employee
from ticket_agent.model_gateway.usage import ModelUsageGuard
from ticket_agent.tickets.domain import TicketStatus, WorkflowState
from ticket_agent.tickets.models import AnswerDraft, Ticket, TicketAnalysis
from ticket_agent.tickets.transitions import transition_ticket
from ticket_agent.tools.execution import ToolExecutionService
from ticket_agent.tools.registry import ToolPermissionError, tool_registry
from ticket_agent.workflow.profile import resolve_knowledge_options


class HROnboardingWorkflow:
    key = "hr_onboarding_document_collection_v1"

    def __init__(self, session: Session) -> None:
        self.session = session
        self.tool_execution = ToolExecutionService(session)

    def process(self, ticket_id: UUID, correlation_id: str) -> None:
        ticket = self.session.scalar(
            select(Ticket).where(Ticket.id == ticket_id).with_for_update()
        )
        if ticket is None or ticket.workflow_state != WorkflowState.RECEIVED:
            return
        employee_service = DigitalEmployeeService(self.session)
        employee = (
            employee_service.get(ticket.employee_id)
            if ticket.employee_id is not None
            else employee_service.ensure_default(ticket.business_unit_id)
        )
        read_call, _definition, _read_payload = self.tool_execution.begin(
            employee=employee,
            tool_key="ticket.read",
            payload={"ticket_id": str(ticket.id)},
            correlation_id=correlation_id,
            ticket_id=ticket.id,
        )
        self.tool_execution.succeed(read_call, {"status": ticket.workflow_state})
        try:
            tool_registry.authorize_all(
                employee,
                {"ticket.read", "knowledge.search", "draft.create"},
            )
        except ToolPermissionError as exc:
            self.tool_execution.record_denied(
                employee=employee,
                tool_key=exc.tool_key,
                payload={},
                correlation_id=correlation_id,
                ticket_id=ticket.id,
                reason_code=exc.code,
            )
            ticket.status = TicketStatus.WAITING_HUMAN
            ticket.needs_human = True
            ticket.human_reason = exc.code
            ticket.version += 1
            self._transition(ticket, WorkflowState.NEEDS_HUMAN, exc.code)
            self._audit(
                ticket,
                correlation_id,
                event_type="tool.permission_denied",
                action=exc.tool_key,
                decision="DENY",
                reason_code=exc.code,
                employee=employee.service_identity,
            )
            self.session.commit()
            return
        usage_guard = ModelUsageGuard(
            self.session,
            employee=employee,
            ticket_id=ticket.id,
            correlation_id=correlation_id,
        )

        self._transition(ticket, WorkflowState.CLASSIFYING, "START_HR_PROCESSING")
        default_scope = employee.knowledge_policy_json.get("default_scope", {})
        scope = {
            str(key): str(value)
            for key, value in default_scope.items()
            if isinstance(value, str)
        }
        for key in ("region", "organization", "org_unit"):
            value = ticket.external_metadata.get(key)
            if isinstance(value, str):
                scope[key] = value

        ticket.category_primary = "hr_onboarding"
        ticket.category_secondary = "document_collection"
        ticket.confidence = 0.95
        ticket.risk_level = "R1"
        ticket.priority = "P2"
        ticket.queue_id = employee.handoff_queue
        ticket.needs_human = False
        ticket.summary = f"入职/调动资料收集任务：{ticket.subject}"
        ticket.version += 1
        self.session.add(
            TicketAnalysis(
                ticket_id=ticket.id,
                ticket_version=ticket.version,
                classifier_name="hr-onboarding-rules-v1",
                category_primary="hr_onboarding",
                category_secondary="document_collection",
                confidence=0.95,
                risk_level="R1",
                priority="P2",
                queue_id=employee.handoff_queue,
                needs_human=False,
                result_json={
                    "reason_codes": ["HR_ONBOARDING_RULE"],
                    "workflow_key": employee.workflow_key,
                },
            )
        )
        self._transition(ticket, WorkflowState.RISK_EVALUATED, "HR_RISK_EVALUATED")
        self._transition(ticket, WorkflowState.ROUTING, "HR_ROUTE")
        knowledge_options = resolve_knowledge_options(employee)
        query = f"入职资料 清单 SOP {ticket.subject}"
        knowledge_call, _definition, knowledge_payload = self.tool_execution.begin(
            employee=employee,
            tool_key="knowledge.search",
            payload={
                "query": query,
                "business_unit_id": ticket.business_unit_id,
                "employee_id": str(employee.id),
                "scope": scope,
                "top_k": knowledge_options.top_k,
                "min_score": knowledge_options.min_score,
            },
            correlation_id=correlation_id,
            ticket_id=ticket.id,
        )
        knowledge_hits = KnowledgeService(
            self.session,
            embedding_provider=get_embedding_provider(usage_guard),
            reranker=build_reranker_for_employee(
                employee,
                usage_guard=usage_guard,
            ),
        ).search(
            query=knowledge_payload["query"],
            business_unit_id=knowledge_payload["business_unit_id"],
            employee_id=employee.id,
            scope=knowledge_payload["scope"],
            top_k=knowledge_options.top_k,
            min_score=knowledge_options.min_score,
        )
        self.tool_execution.succeed(
            knowledge_call,
            {"result_count": len(knowledge_hits)},
        )
        if not knowledge_hits:
            ticket.status = TicketStatus.WAITING_HUMAN
            ticket.needs_human = True
            ticket.human_reason = "HR_SOP_NOT_FOUND"
            self._transition(ticket, WorkflowState.NEEDS_HUMAN, "HR_SOP_NOT_FOUND")
            self._audit(
                ticket,
                correlation_id,
                event_type="ticket.human_required",
                action="escalate",
                decision="EXECUTED",
                reason_code="HR_SOP_NOT_FOUND",
                employee=employee.service_identity,
            )
            self.session.commit()
            return

        top_hit = knowledge_hits[0]
        citation = {
            "chunk_id": str(top_hit.chunk_id),
            "document_id": str(top_hit.document_id),
            "title": top_hit.title,
            "version": top_hit.version,
        }
        draft_text = (
            "您好，已收到您的入职资料收集任务。"
            f"已匹配现行指引《{top_hit.title}》v{top_hit.version}，"
            "HR 将按该版本核对资料。如需补充，会在本任务中通知您。"
        )
        claims = [
            {
                "text": "您好，已收到您的入职资料收集任务。",
                "claim_type": "greeting",
                "cited_chunk_ids": [],
            },
            {
                "text": f"已匹配现行指引《{top_hit.title}》v{top_hit.version}。",
                "claim_type": "policy",
                "cited_chunk_ids": [str(top_hit.chunk_id)],
            },
            {
                "text": "HR 将按该版本核对资料，如需补充会在本任务中通知您。",
                "claim_type": "instruction",
                "cited_chunk_ids": [str(top_hit.chunk_id)],
            },
        ]
        self._transition(ticket, WorkflowState.DRAFTING, "HR_GENERATE_DRAFT")
        draft_call, _definition, _draft_payload = self.tool_execution.begin(
            employee=employee,
            tool_key="draft.create",
            payload={
                "ticket_id": str(ticket.id),
                "text": draft_text,
                "citation_count": 1,
                "claim_count": len(claims),
            },
            correlation_id=correlation_id,
            ticket_id=ticket.id,
        )
        self.session.add(
            AnswerDraft(
                ticket_id=ticket.id,
                text=draft_text,
                citations_json=[citation],
                claims_json=claims,
                generator_provider="local",
                generator_model="hr-onboarding-template-v1",
                grounding_status="GROUNDED",
            )
        )
        self.tool_execution.succeed(
            draft_call,
            {"citation_count": 1, "claim_count": len(claims)},
        )
        ticket.status = TicketStatus.IN_PROGRESS
        self._transition(ticket, WorkflowState.PENDING_REVIEW, "HR_DRAFT_READY")
        self._audit(
            ticket,
            correlation_id,
            event_type="draft.created",
            action="create_draft",
            decision="EXECUTED",
            reason_code="HR_ONBOARDING_RULE",
            employee=employee.service_identity,
            payload={"citation_count": 1},
        )
        self.session.commit()

    def _transition(
        self,
        ticket: Ticket,
        target: WorkflowState,
        reason_code: str,
    ) -> None:
        transition_ticket(
            self.session,
            ticket,
            target,
            reason_code=reason_code,
            actor_id="digital_employee.hr_onboarding",
        )

    def _audit(
        self,
        ticket: Ticket,
        correlation_id: str,
        *,
        event_type: str,
        action: str,
        decision: str,
        reason_code: str,
        employee: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type=event_type,
            actor_type="SERVICE",
            actor_id=employee,
            resource_id=ticket.id,
            action=action,
            decision=decision,
            reason_code=reason_code,
            payload=payload,
        )


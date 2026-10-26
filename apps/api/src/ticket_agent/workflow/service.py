from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ticket_agent.audit.service import record_audit
from ticket_agent.classification.classifier import AnalysisResult
from ticket_agent.digital_employees.service import DigitalEmployeeService
from ticket_agent.ecommerce.models import EcommerceCategoryProfile
from ticket_agent.knowledge.embedding_factory import get_embedding_provider
from ticket_agent.knowledge.models import KnowledgeFeedback, KnowledgeRepairTask
from ticket_agent.knowledge.service import KnowledgeService
from ticket_agent.model_gateway.profile import (
    build_classifier_for_employee,
    build_draft_service_for_employee,
    build_reranker_for_employee,
)
from ticket_agent.model_gateway.usage import ModelUsageGuard
from ticket_agent.routing.policy import get_routing_policy
from ticket_agent.shared.settings import get_settings
from ticket_agent.tickets.domain import (
    RiskLevel,
    TicketStatus,
    WorkflowState,
)
from ticket_agent.tickets.drafts import DraftResult
from ticket_agent.tickets.models import (
    AnswerDraft,
    OutboxEvent,
    Ticket,
    TicketAnalysis,
)
from ticket_agent.tickets.transitions import transition_ticket
from ticket_agent.tools.execution import ToolExecutionService
from ticket_agent.tools.registry import ToolPermissionError, tool_registry
from ticket_agent.workflow.profile import resolve_knowledge_options

AUTO_REPLY_BLOCKED_TERMS = {
    "退款",
    "退货",
    "赔付",
    "补偿",
    "转账",
    "银行卡",
    "身份证",
    "密码",
    "验证码",
}


class WorkflowService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.routing_policy = get_routing_policy()
        self.tool_execution = ToolExecutionService(session)

    def process(self, ticket_id: UUID, correlation_id: str) -> None:
        ticket = self.session.scalar(
            select(Ticket).where(Ticket.id == ticket_id).with_for_update()
        )
        if ticket is None:
            return
        if ticket.workflow_state != WorkflowState.RECEIVED:
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
            record_audit(
                self.session,
                correlation_id=correlation_id,
                event_type="tool.permission_denied",
                actor_type="SERVICE",
                actor_id=employee.service_identity,
                resource_id=ticket.id,
                action=exc.tool_key,
                decision="DENY",
                reason_code=exc.code,
            )
            self.session.commit()
            return

        self._transition(ticket, WorkflowState.CLASSIFYING, "START_PROCESSING")
        usage_guard = ModelUsageGuard(
            self.session,
            employee=employee,
            ticket_id=ticket.id,
            correlation_id=correlation_id,
        )
        classifier = build_classifier_for_employee(
            employee,
            usage_guard=usage_guard,
        )
        analysis = classifier.classify(
            subject=ticket.subject,
            body=ticket.body,
            customer_tier=ticket.customer_tier,
        )
        analysis = self._apply_category_profile(analysis, ticket)
        routing = self.routing_policy.decide(analysis)

        ticket.summary = analysis.summary
        ticket.category_primary = analysis.category_primary
        ticket.category_secondary = analysis.category_secondary
        ticket.confidence = analysis.confidence
        ticket.risk_level = analysis.risk_level
        ticket.priority = routing.priority
        ticket.queue_id = routing.queue_id
        ticket.needs_human = routing.needs_human
        ticket.human_reason = routing.human_reason
        ticket.version += 1

        self.session.add(
            TicketAnalysis(
                ticket_id=ticket.id,
                ticket_version=ticket.version,
                classifier_name=analysis.model_name,
                category_primary=analysis.category_primary,
                category_secondary=analysis.category_secondary,
                confidence=analysis.confidence,
                risk_level=analysis.risk_level,
                priority=routing.priority,
                queue_id=routing.queue_id,
                needs_human=routing.needs_human,
                result_json={
                    "risk_tags": analysis.risk_tags,
                    "reason_codes": routing.reason_codes,
                    "matched_rule_id": routing.matched_rule_id,
                    "human_reason": routing.human_reason,
                    "model_provider": analysis.model_provider,
                    "model_name": analysis.model_name,
                    "fallback_used": analysis.fallback_used,
                },
            )
        )

        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="ticket.classified",
            actor_type="SERVICE",
            actor_id="digital_agent.ticket.v1",
            on_behalf_of=ticket.requester_ref,
            resource_id=ticket.id,
            action="classify",
            decision="EXECUTED",
            payload={
                "category_primary": analysis.category_primary,
                "category_secondary": analysis.category_secondary,
                "confidence": analysis.confidence,
                "risk_level": analysis.risk_level,
            },
        )
        self._transition(ticket, WorkflowState.RISK_EVALUATED, "RISK_EVALUATED")
        self._transition(ticket, WorkflowState.ROUTING, "ROUTE_TICKET")

        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="ticket.routed",
            actor_type="SERVICE",
            actor_id="digital_agent.ticket.v1",
            on_behalf_of=ticket.requester_ref,
            resource_id=ticket.id,
            action="route",
            decision="EXECUTED",
            reason_code=routing.matched_rule_id,
            payload={
                "queue_id": routing.queue_id,
                "priority": routing.priority,
                "needs_human": routing.needs_human,
                "reason_codes": routing.reason_codes,
            },
        )

        auto_reply_eligible = False
        auto_reply_text = ""
        if routing.needs_human:
            ticket.status = TicketStatus.WAITING_HUMAN
            self._transition(
                ticket,
                WorkflowState.NEEDS_HUMAN,
                routing.human_reason or "HUMAN_REVIEW_REQUIRED",
            )
            record_audit(
                self.session,
                correlation_id=correlation_id,
                event_type="ticket.human_required",
                actor_type="SERVICE",
                actor_id="digital_agent.ticket.v1",
                resource_id=ticket.id,
                action="escalate",
                decision="EXECUTED",
                reason_code=routing.human_reason or "HUMAN_REVIEW_REQUIRED",
            )
        else:
            self._transition(ticket, WorkflowState.DRAFTING, "GENERATE_DRAFT")
            employee_scope = employee.knowledge_policy_json.get("default_scope", {})
            knowledge_options = resolve_knowledge_options(employee)
            knowledge_scope = (
                {
                    **{
                        str(key): str(value)
                        for key, value in employee_scope.items()
                        if isinstance(value, str)
                    },
                    "audience": "support_agent",
                }
                | {
                    key: value
                    for key in (
                        "product",
                        "region",
                        "audience",
                        "organization",
                        "org_unit",
                        "product_id",
                        "sku",
                    )
                    if isinstance((value := ticket.external_metadata.get(key)), str)
                }
            )
            knowledge_call, _definition, knowledge_payload = self.tool_execution.begin(
                employee=employee,
                tool_key="knowledge.search",
                payload={
                    "query": f"{ticket.subject}\n{ticket.body}",
                    "business_unit_id": ticket.business_unit_id,
                    "employee_id": str(employee.id),
                    "scope": knowledge_scope,
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
            if (
                not knowledge_hits
                and analysis.category_primary == "ecommerce_presales"
            ):
                repair = KnowledgeRepairTask(
                    business_unit_id=ticket.business_unit_id,
                    status="OPEN",
                    priority="P1",
                    title=f"知识零命中：{ticket.subject}"[:300],
                    query=f"{ticket.subject}\n{ticket.body}",
                    expected_titles_json=[],
                    returned_titles_json=[],
                    created_by="system.knowledge_gap",
                )
                self.session.add(repair)
                self.session.flush()
                self.session.add(
                    KnowledgeFeedback(
                        business_unit_id=ticket.business_unit_id,
                        employee_id=employee.id,
                        ticket_id=ticket.id,
                        query=f"{ticket.subject}\n{ticket.body}",
                        answer="",
                        rating="NEGATIVE",
                        reason_code="MISSING_KNOWLEDGE",
                        details="售前知识检索零命中，已阻止无依据回答",
                        repair_task_id=repair.id,
                        created_by="system.knowledge_gap",
                    )
                )
                ticket.status = TicketStatus.WAITING_HUMAN
                ticket.needs_human = True
                ticket.human_reason = "KNOWLEDGE_NOT_FOUND"
                self._transition(
                    ticket,
                    WorkflowState.NEEDS_HUMAN,
                    "KNOWLEDGE_NOT_FOUND",
                )
                self.session.commit()
                return
            draft_service = build_draft_service_for_employee(
                employee,
                usage_guard=usage_guard,
            )
            draft_result = draft_service.generate(
                subject=ticket.subject,
                body=ticket.body,
                analysis=analysis,
                routing=routing,
                knowledge_hits=knowledge_hits,
            )
            draft_call, _definition, _draft_payload = self.tool_execution.begin(
                employee=employee,
                tool_key="draft.create",
                payload={
                    "ticket_id": str(ticket.id),
                    "text": draft_result.text,
                    "citation_count": len(draft_result.citations),
                    "claim_count": len(draft_result.claims),
                },
                correlation_id=correlation_id,
                ticket_id=ticket.id,
            )
            draft = AnswerDraft(
                ticket_id=ticket.id,
                text=draft_result.text,
                citations_json=draft_result.citations,
                claims_json=draft_result.claims,
                generator_provider=draft_result.provider,
                generator_model=draft_result.model,
                grounding_status=draft_result.grounding_status,
            )
            self.session.add(draft)
            self.tool_execution.succeed(
                draft_call,
                {
                    "citation_count": len(draft_result.citations),
                    "claim_count": len(draft_result.claims),
                },
            )
            record_audit(
                self.session,
                correlation_id=correlation_id,
                event_type="draft.created",
                actor_type="SERVICE",
                actor_id="digital_agent.ticket.v1",
                resource_id=ticket.id,
                action="create_draft",
                decision="EXECUTED",
                payload={
                    "citation_count": len(draft_result.citations),
                    "generator_provider": draft_result.provider,
                    "generator_model": draft_result.model,
                    "fallback_used": draft_result.fallback_used,
                    "grounding_status": draft_result.grounding_status,
                },
            )
            auto_reply_eligible, decision_reason = self._auto_reply_decision(
                ticket,
                draft_result,
                employee.tool_allowlist_json,
            )
            if auto_reply_eligible:
                self._prepare_auto_approval(
                    ticket=ticket,
                    draft=draft,
                    draft_result=draft_result,
                    employee_identity=employee.service_identity,
                    correlation_id=correlation_id,
                    decision_reason=decision_reason,
                )
                auto_reply_text = draft_result.text
            else:
                ticket.status = TicketStatus.IN_PROGRESS
                self._transition(
                    ticket,
                    WorkflowState.PENDING_REVIEW,
                    "DRAFT_READY",
                )

        self.session.commit()
        if auto_reply_eligible:
            from ticket_agent.customer_service.service import (
                CustomerConversationService,
            )

            CustomerConversationService(
                self.session
            ).append_assistant_reply(ticket.id, auto_reply_text)

    def _auto_reply_decision(
        self,
        ticket: Ticket,
        draft_result: DraftResult,
        allowed_tools: list[str],
    ) -> tuple[bool, str]:
        settings = get_settings()
        if not settings.customer_service_auto_reply_enabled:
            return False, "AUTO_REPLY_DISABLED"
        if draft_result.fallback_used:
            return False, "AUTO_REPLY_FALLBACK_USED"
        if "ticket.sync" not in allowed_tools:
            return False, "AUTO_REPLY_SYNC_NOT_AUTHORIZED"
        if ticket.category_primary != "ecommerce_presales":
            return False, "AUTO_REPLY_CATEGORY_NOT_ALLOWED"
        if ticket.risk_level != RiskLevel.R0 or ticket.needs_human:
            return False, "AUTO_REPLY_RISK_NOT_ALLOWED"
        if (ticket.confidence or 0.0) < (
            settings.customer_service_auto_reply_min_confidence
        ):
            return False, "AUTO_REPLY_CONFIDENCE_TOO_LOW"
        if not draft_result.citations:
            return False, "AUTO_REPLY_NO_CITATION"
        if any(
            str(claim.get("verification_verdict", "")).lower()
            in {"unsupported", "uncertain"}
            for claim in draft_result.claims
        ):
            return False, "AUTO_REPLY_CLAIM_NOT_SUPPORTED"
        cited_claims = [
            claim
            for claim in draft_result.claims
            if claim.get("cited_chunk_ids")
        ]
        if not cited_claims:
            return False, "AUTO_REPLY_NO_VERIFIED_CLAIM"
        verdicts = {
            str(claim.get("verification_verdict", "")).lower()
            for claim in cited_claims
        }
        if verdicts != {"supported"}:
            return False, "AUTO_REPLY_CLAIM_UNVERIFIED"
        if draft_result.grounding_status != "GROUNDED":
            return False, "AUTO_REPLY_NOT_GROUNDED"
        if not draft_result.text.strip():
            return False, "AUTO_REPLY_EMPTY"
        if len(draft_result.text) > (
            settings.customer_service_auto_reply_max_characters
        ):
            return False, "AUTO_REPLY_TOO_LONG"
        conversation_text = f"{ticket.subject}\n{ticket.body}\n{draft_result.text}"
        if any(term in conversation_text for term in AUTO_REPLY_BLOCKED_TERMS):
            return False, "AUTO_REPLY_SENSITIVE_ACTION"
        return True, "LOW_RISK_GROUNDED_PRESALES"

    def _prepare_auto_approval(
        self,
        *,
        ticket: Ticket,
        draft: AnswerDraft,
        draft_result: DraftResult,
        employee_identity: str,
        correlation_id: str,
        decision_reason: str,
    ) -> None:
        draft.status = "AUTO_ACCEPTED"
        draft.reviewed_at = datetime.now(UTC)
        ticket.status = TicketStatus.IN_PROGRESS
        ticket.sync_status = "PENDING"
        ticket.sync_attempts = 0
        ticket.sync_error = None
        ticket.version += 1
        self._transition(
            ticket,
            WorkflowState.SYNCING,
            decision_reason,
        )
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
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="draft.auto_approved",
            actor_type="SERVICE",
            actor_id=employee_identity,
            resource_id=ticket.id,
            action="auto_review",
            decision="EXECUTED",
            reason_code=decision_reason,
            payload={
                "draft_id": str(draft.id),
                "category": ticket.category_primary,
                "risk_level": ticket.risk_level,
                "confidence": ticket.confidence,
                "grounding_status": draft_result.grounding_status,
                "citation_count": len(draft_result.citations),
                "sync_requested": True,
            },
        )

    def _apply_category_profile(
        self,
        analysis: AnalysisResult,
        ticket: Ticket,
    ) -> AnalysisResult:
        if (
            analysis.risk_level == RiskLevel.R3
            or analysis.category_primary == "data_privacy_security"
        ):
            return analysis
        category_name = ticket.external_metadata.get("category")
        if not isinstance(category_name, str):
            return analysis
        profile = self.session.scalar(
            select(EcommerceCategoryProfile).where(
                EcommerceCategoryProfile.business_unit_id
                == ticket.business_unit_id,
                EcommerceCategoryProfile.name == category_name,
                EcommerceCategoryProfile.status == "ACTIVE",
            )
        )
        if profile is None:
            return analysis
        text = f"{ticket.subject}\n{ticket.body}"
        if any(keyword in text for keyword in profile.aftersales_keywords_json):
            return replace(
                analysis,
                category_primary="ecommerce_aftersales",
                category_secondary="category_after_sales",
                confidence=max(analysis.confidence, 0.93),
                risk_level=analysis.risk_level,
                needs_human=True,
                human_reason=(
                    analysis.human_reason
                    if analysis.risk_level in {RiskLevel.R2, RiskLevel.R3}
                    else "AFTER_SALES_REQUIRES_HUMAN"
                ),
                reason_codes=[
                    *analysis.reason_codes,
                    "CATEGORY_AFTERSALES_KEYWORD",
                ],
            )
        if (
            analysis.risk_level not in {RiskLevel.R2, RiskLevel.R3}
            and any(
                keyword in text
                for keyword in profile.presales_keywords_json
            )
        ):
            return replace(
                analysis,
                category_primary="ecommerce_presales",
                category_secondary="category_presales",
                confidence=max(analysis.confidence, 0.94),
                risk_level=RiskLevel.R0,
                needs_human=False,
                human_reason=None,
                reason_codes=[
                    *analysis.reason_codes,
                    "CATEGORY_PRESALES_KEYWORD",
                ],
            )
        return analysis

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
            actor_id="digital_agent.ticket.v1",
        )


import json
import re
from collections.abc import Callable
from typing import Any, Literal, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from ticket_agent.agent_skills.service import AgentSkillService
from ticket_agent.audit.service import record_audit
from ticket_agent.classification.classifier import AnalysisResult
from ticket_agent.classification.conversation_signals import (
    is_technical_documentation_question as _is_technical_documentation_question,
)
from ticket_agent.classification.conversation_signals import (
    repository_name as _repository_name,
)
from ticket_agent.customer_service.models import (
    ConversationMemory,
    CustomerConversation,
    CustomerMessage,
)
from ticket_agent.customer_service.schemas import CustomerReplySuggestionView
from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.digital_employees.service import DigitalEmployeeService
from ticket_agent.knowledge.embedding_factory import get_embedding_provider
from ticket_agent.knowledge.service import KnowledgeHit, KnowledgeService
from ticket_agent.mcp_connectors.runtime import (
    McpExecutionResult,
    McpToolRuntime,
    McpToolTarget,
)
from ticket_agent.model_gateway.profile import (
    build_draft_service_for_employee,
    build_reranker_for_employee,
    build_tool_planner_for_employee,
)
from ticket_agent.model_gateway.types import ModelGatewayError, ToolPlan
from ticket_agent.model_gateway.usage import ModelUsageGuard
from ticket_agent.routing.policy import RoutingDecision
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.tickets.domain import Priority, RiskLevel
from ticket_agent.tickets.drafts import DraftEvidence, DraftResult
from ticket_agent.tickets.models import Ticket
from ticket_agent.tools.execution import ToolExecutionService
from ticket_agent.tools.registry import ToolPermissionError
from ticket_agent.workflow.profile import resolve_knowledge_options


class CustomerSuggestionState(TypedDict, total=False):
    conversation_id: UUID
    requested_by: str
    query: str
    repository: str | None
    skill: str
    skill_instructions: str
    skill_name: str
    employee: DigitalEmployee
    ticket: Ticket
    usage_guard: ModelUsageGuard
    knowledge_hits: list[KnowledgeHit]
    mcp_plan: ToolPlan | None
    mcp_evidence: list[DraftEvidence]
    mcp_tool_calls: list[McpExecutionResult]
    draft: DraftResult
    trace: list[str]


class CustomerReplySuggestionService:
    def __init__(
        self,
        session: Session,
        *,
        on_stage: Callable[[str], None] | None = None,
        on_text_delta: Callable[[str], None] | None = None,
    ) -> None:
        self.session = session
        self.tool_execution = ToolExecutionService(session)
        self.mcp_runtime = McpToolRuntime(session)
        self._on_stage = on_stage
        self._on_text_delta = on_text_delta
        self.graph = self._build_graph()

    def _emit_stage(self, label: str) -> None:
        if self._on_stage is not None:
            self._on_stage(label)

    def _build_graph(self) -> Any:
        graph = StateGraph(CustomerSuggestionState)
        graph.add_node("route_skill", self._route_skill)
        graph.add_node("retrieve_knowledge", self._retrieve_knowledge)
        graph.add_node("plan_mcp_tools", self._plan_mcp_tools)
        graph.add_node("execute_mcp_tool", self._execute_mcp_tool)
        graph.add_node("generate_reply", self._generate_reply)
        graph.add_edge(START, "route_skill")
        graph.add_edge("route_skill", "retrieve_knowledge")
        graph.add_edge("retrieve_knowledge", "plan_mcp_tools")
        graph.add_conditional_edges(
            "plan_mcp_tools",
            self._after_tool_plan,
            {
                "execute": "execute_mcp_tool",
                "generate": "generate_reply",
                "finish": END,
            },
        )
        graph.add_conditional_edges(
            "execute_mcp_tool",
            self._after_tool_execution,
            {
                "generate": "generate_reply",
                "finish": END,
            },
        )
        graph.add_edge("generate_reply", END)
        return graph.compile()

    def generate(
        self,
        conversation_id: UUID,
        *,
        agent_id: str,
        correlation_id: str,
        persist_reply: bool = True,
    ) -> CustomerReplySuggestionView:
        conversation = self.session.get(CustomerConversation, conversation_id)
        if conversation is None:
            raise ApiProblem(
                status_code=404,
                code="CONVERSATION_NOT_FOUND",
                title="Conversation not found",
                detail="The conversation does not exist.",
            )
        if (
            conversation.assigned_agent_id is not None
            and conversation.assigned_agent_id != agent_id
        ):
            raise ApiProblem(
                status_code=409,
                code="CONVERSATION_ASSIGNED_TO_ANOTHER_AGENT",
                title="Conversation belongs to another agent",
                detail=(
                    "Reply suggestions are read-only, but this conversation "
                    "is already being handled by another agent."
                ),
            )
        ticket = (
            self.session.get(Ticket, conversation.current_ticket_id)
            if conversation.current_ticket_id
            else None
        )
        if ticket is None:
            raise ApiProblem(
                status_code=409,
                code="CONVERSATION_TICKET_NOT_FOUND",
                title="Conversation has no current ticket",
                detail="A reply suggestion requires an active conversation ticket.",
            )
        query = self._query(conversation.id)
        security_refusal = _security_boundary_refusal(
            _latest_buyer_question(query)
        )
        if security_refusal is not None:
            record_audit(
                self.session,
                correlation_id=correlation_id,
                event_type=(
                    "customer_service.reply_suggestion.security_blocked"
                ),
                actor_type="USER",
                actor_id=agent_id,
                resource_type="customer_conversation",
                resource_id=conversation.id,
                action="generate_reply_suggestion",
                decision="REJECTED",
                reason_code="SENSITIVE_DATA_BOUNDARY",
                payload={"ticket_id": str(ticket.id)},
            )
            self.session.commit()
            if persist_reply and conversation.channel.startswith("enterprise"):
                from ticket_agent.customer_service.service import (
                    CustomerConversationService,
                )

                CustomerConversationService(
                    self.session
                ).append_assistant_reply(ticket.id, security_refusal)
            return CustomerReplySuggestionView(
                text=security_refusal,
                provider="security_policy",
                model="deterministic-refusal-v1",
                fallback_used=False,
                grounding_status="POLICY_BLOCKED",
                citations=[],
                skill="developer-repository-support",
                trace=[
                    "security_guard → 拒绝私有仓库和敏感凭据访问",
                    "tool_execution → 未调用 DeepWiki 或其他业务工具",
                ],
                tool_calls=[],
            )
        employee_service = DigitalEmployeeService(self.session)
        employee = (
            employee_service.get(ticket.employee_id)
            if ticket.employee_id
            else employee_service.ensure_default(ticket.business_unit_id)
        )
        usage_guard = ModelUsageGuard(
            self.session,
            employee=employee,
            ticket_id=ticket.id,
            correlation_id=correlation_id,
        )
        memory = self.session.get(ConversationMemory, conversation.id)
        stored_repository = (
            _repository_name(str(memory.slots_json.get("repository")))
            if memory is not None
            else None
        )
        repository = _resolved_repository(
            query,
            stored_repository,
        )
        try:
            state = self.graph.invoke(
                {
                    "conversation_id": conversation.id,
                    "requested_by": agent_id,
                    "query": query,
                    "repository": repository,
                    "employee": employee,
                    "ticket": ticket,
                    "usage_guard": usage_guard,
                    "mcp_evidence": [],
                    "mcp_tool_calls": [],
                    "trace": [],
                }
            )
        except ToolPermissionError as exc:
            raise ApiProblem(
                status_code=403,
                code=exc.code,
                title="Tool permission denied",
                detail=f"The digital employee cannot use {exc.tool_key}.",
            ) from exc

        trace = [str(item) for item in state.get("trace", [])]
        skill = str(state.get("skill") or "customer-service-general")
        tool_calls = state.get("mcp_tool_calls", [])
        tool_call_views = [
            {
                "tool_call_id": item.tool_call_id,
                "tool_id": item.tool_id,
                "status": item.status,
                "is_write": item.is_write,
                "duration_ms": item.duration_ms,
                "error_code": item.error_code,
                "approval_id": (
                    str(item.approval_id)
                    if item.approval_id
                    else None
                ),
                "approval_required_role": item.approval_required_role,
            }
            for item in tool_calls
        ]
        draft = state.get("draft")
        if not isinstance(draft, DraftResult):
            approval_call = next(
                (
                    item
                    for item in tool_calls
                    if item.status == "APPROVAL_REQUIRED"
                    and item.approval_id is not None
                ),
                None,
            )
            if approval_call is not None:
                record_audit(
                    self.session,
                    correlation_id=correlation_id,
                    event_type="customer_service.reply_suggestion.approval_required",
                    actor_type="USER",
                    actor_id=agent_id,
                    resource_type="customer_conversation",
                    resource_id=conversation.id,
                    action="generate_reply_suggestion",
                    decision="PENDING_APPROVAL",
                    reason_code="MCP_WRITE_REQUIRES_APPROVAL",
                    payload={
                        "ticket_id": str(ticket.id),
                        "skill": skill,
                        "graph_trace": trace,
                        "approval_id": str(approval_call.approval_id),
                        "tool_id": approval_call.tool_id,
                    },
                )
                self.session.commit()
                return CustomerReplySuggestionView(
                    text=(
                        "该操作包含外部写入，已创建独立人工审批单 "
                        f"{approval_call.approval_id}。审批通过并执行前，"
                        "系统不会调用写工具或对外产生业务变更。"
                    ),
                    provider="system_policy",
                    model="mcp-approval-gate",
                    fallback_used=False,
                    grounding_status="APPROVAL_REQUIRED",
                    citations=[],
                    skill=skill,
                    trace=trace,
                    tool_calls=tool_call_views,
                )
            self.session.commit()
            raise ApiProblem(
                status_code=409,
                code="KNOWLEDGE_NOT_FOUND",
                title="No grounded knowledge found",
                detail="No knowledge supports a reply suggestion for this conversation.",
            )
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="customer_service.reply_suggestion.generated",
            actor_type="USER",
            actor_id=agent_id,
            resource_type="customer_conversation",
            resource_id=conversation.id,
            action="generate_reply_suggestion",
            decision="EXECUTED",
            payload={
                "ticket_id": str(ticket.id),
                "provider": draft.provider,
                "model": draft.model,
                "fallback_used": draft.fallback_used,
                "citation_count": len(draft.citations),
                "skill": skill,
                "graph_trace": trace,
                "mcp_tool_calls": [
                    {
                        "tool_call_id": str(item.tool_call_id),
                        "tool_id": item.tool_id,
                        "status": item.status,
                        "approval_id": (
                            str(item.approval_id)
                            if item.approval_id
                            else None
                        ),
                    }
                    for item in tool_calls
                ],
            },
        )
        persist_for_multi_turn = (
            conversation.channel.startswith("enterprise")
            and not ticket.needs_human
            and (ticket.risk_level or "R1") in {"R0", "R1"}
            and draft.grounding_status == "GROUNDED"
        )
        self.session.commit()
        if persist_reply and persist_for_multi_turn:
            from ticket_agent.customer_service.service import (
                CustomerConversationService,
            )

            CustomerConversationService(
                self.session
            ).append_assistant_reply(ticket.id, draft.text)
        return CustomerReplySuggestionView(
            text=draft.text,
            provider=draft.provider,
            model=draft.model,
            fallback_used=draft.fallback_used,
            grounding_status=draft.grounding_status,
            citations=draft.citations,
            skill=skill,
            trace=trace,
            tool_calls=tool_call_views,
        )

    def _route_skill(self, state: CustomerSuggestionState) -> dict[str, Any]:
        self._emit_stage("正在匹配岗位 Skill")
        query = _latest_buyer_question(state["query"]).lower()
        ticket = state["ticket"]
        employee = state["employee"]
        skills = AgentSkillService(self.session).resolve_employee_skills(
            employee.id,
            employee.business_unit_id,
        )
        expected_skill = {
            "ecommerce_presales": "ecommerce-presales",
            "ecommerce_aftersales": "ecommerce-aftersales",
        }.get(ticket.category_primary or "")
        scored = [
            (
                skill,
                sum(
                    1
                    for trigger in skill.triggers
                    if trigger.lower() in query
                    or trigger == ticket.category_primary
                ),
            )
            for skill in skills
        ]
        score_by_code = {skill.code: score for skill, score in scored}
        logistics_skill = next(
            (
                skill
                for skill in skills
                if skill.code == "logistics-inquiry"
                and score_by_code.get(skill.code, 0) > 0
            ),
            None,
        )
        category_skill = next(
            (
                skill
                for skill in skills
                if skill.code == expected_skill
                and score_by_code.get(skill.code, 0) > 0
            ),
            None,
        )
        matched_candidates = [
            (skill, score)
            for skill, score in scored
            if score > 0
        ]
        matched = (
            logistics_skill
            or category_skill
            or (
                max(
                    matched_candidates,
                    key=lambda item: item[1],
                )[0]
                if matched_candidates
                else skills[0] if skills else None
            )
        )
        if matched is None:
            raise ApiProblem(
                status_code=409,
                code="SKILL_NOT_CONFIGURED",
                title="No employee skill is configured",
                detail="Bind at least one ACTIVE skill to the digital employee.",
            )
        return {
            "skill": matched.code,
            "skill_name": matched.name,
            "skill_instructions": matched.instructions,
            "trace": [
                *state.get("trace", []),
                f"route_skill → {matched.code}",
            ],
        }

    def _retrieve_knowledge(
        self,
        state: CustomerSuggestionState,
    ) -> dict[str, Any]:
        self._emit_stage("正在检索知识与业务资料")
        employee = state["employee"]
        ticket = state["ticket"]
        usage_guard = state["usage_guard"]
        options = resolve_knowledge_options(employee)
        employee_scope = employee.knowledge_policy_json.get(
            "default_scope",
            {},
        )
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
                    "organization",
                    "org_unit",
                    "product_id",
                    "sku",
                )
                if isinstance(
                    (value := ticket.external_metadata.get(key)),
                    str,
                )
            }
        )
        call, _, payload = self.tool_execution.begin(
            employee=employee,
            tool_key="knowledge.search",
            payload={
                "query": state["query"],
                "business_unit_id": ticket.business_unit_id,
                "employee_id": str(employee.id),
                "scope": knowledge_scope,
                "top_k": options.top_k,
                "min_score": options.min_score,
            },
            correlation_id=usage_guard.correlation_id,
            ticket_id=ticket.id,
        )
        hits = KnowledgeService(
            self.session,
            embedding_provider=get_embedding_provider(usage_guard),
            reranker=build_reranker_for_employee(
                employee,
                usage_guard=usage_guard,
            ),
        ).search(
            query=payload["query"],
            business_unit_id=payload["business_unit_id"],
            employee_id=employee.id,
            scope=payload["scope"],
            top_k=options.top_k,
            min_score=options.min_score,
        )
        if _is_technical_documentation_question(payload["query"]):
            hits = [
                hit
                for hit in hits
                if _technical_knowledge_hit_matches(
                    hit,
                    str(payload["query"]),
                )
            ]
        self.tool_execution.succeed(
            call,
            {"result_count": len(hits)},
        )
        return {
            "knowledge_hits": hits,
            "trace": [
                *state.get("trace", []),
                f"retrieve_knowledge → {len(hits)} 条知识",
            ],
        }

    def _plan_mcp_tools(
        self,
        state: CustomerSuggestionState,
    ) -> dict[str, Any]:
        self._emit_stage("正在规划业务工具")
        employee = state["employee"]
        available = self.mcp_runtime.available_tools(employee)
        trace = list(state.get("trace", []))
        if not available:
            return {
                "mcp_plan": None,
                "trace": trace,
            }
        if (
            _is_technical_documentation_question(state["query"])
            and _repository_name(state["query"]) is None
        ):
            return {
                "mcp_plan": None,
                "trace": [
                    *trace,
                    "plan_mcp_tools → 未提供 owner/repo，仅使用 RAG 知识",
                ],
            }
        fast_plan = _technical_documentation_plan(
            state["query"],
            available,
            context_repository=state.get("repository"),
        )
        if fast_plan is not None:
            return {
                "mcp_plan": fast_plan,
                "trace": [
                    *trace,
                    f"plan_mcp_tools → {fast_plan.tool_id} · 确定性快路径",
                ],
            }
        planner = build_tool_planner_for_employee(
            employee,
            usage_guard=state["usage_guard"],
        )
        if planner is None:
            return {
                "mcp_plan": None,
                "trace": [
                    *trace,
                    "plan_mcp_tools → 本地模型未启用工具规划",
                ],
            }
        try:
            plan = planner.plan_tool(
                query=state["query"],
                subject=state["ticket"].subject,
                skill_name=state.get("skill_name", state["skill"]),
                skill_instructions=state.get("skill_instructions", ""),
                tools=[target.spec for target in available],
            )
        except (ModelGatewayError, ValueError) as exc:
            return {
                "mcp_plan": None,
                "trace": [
                    *trace,
                    f"plan_mcp_tools → 规划失败 {type(exc).__name__}",
                ],
            }
        if plan.tool_id is None:
            return {
                "mcp_plan": plan,
                "trace": [*trace, "plan_mcp_tools → 无需实时工具"],
            }
        return {
            "mcp_plan": plan,
            "trace": [*trace, f"plan_mcp_tools → {plan.tool_id}"],
        }

    def _execute_mcp_tool(
        self,
        state: CustomerSuggestionState,
    ) -> dict[str, Any]:
        plan = state.get("mcp_plan")
        if plan is None or plan.tool_id is None:
            return {}
        self._emit_stage("正在调用业务工具获取实时结果")
        employee = state["employee"]
        ticket = state["ticket"]
        try:
            result = self.mcp_runtime.execute(
                employee=employee,
                tool_id=plan.tool_id,
                arguments=plan.arguments,
                correlation_id=state["usage_guard"].correlation_id,
                ticket_id=ticket.id,
                requested_by=state["requested_by"],
                conversation_id=state["conversation_id"],
                reason=plan.reason,
            )
        except ValueError as exc:
            return {
                "trace": [
                    *state.get("trace", []),
                    f"execute_mcp_tool → 拒绝 {str(exc)[:160]}",
                ],
            }
        evidence = result.evidence
        status_detail = (
            "需人工审批"
            if result.status == "APPROVAL_REQUIRED"
            else result.status
        )
        return {
            "mcp_tool_calls": [*state.get("mcp_tool_calls", []), result],
            "mcp_evidence": (
                [*state.get("mcp_evidence", []), evidence]
                if evidence is not None
                else state.get("mcp_evidence", [])
            ),
            "trace": [
                *state.get("trace", []),
                f"execute_mcp_tool → {result.tool_id} · {status_detail}",
            ],
        }

    def _after_tool_plan(
        self,
        state: CustomerSuggestionState,
    ) -> Literal["execute", "generate", "finish"]:
        plan = state.get("mcp_plan")
        if plan is not None and plan.tool_id is not None:
            return "execute"
        if _is_technical_documentation_question(state["query"]):
            return "generate"
        return "generate" if state.get("knowledge_hits") else "finish"

    def _after_tool_execution(
        self,
        state: CustomerSuggestionState,
    ) -> Literal["generate", "finish"]:
        if _is_technical_documentation_question(state["query"]):
            return "generate"
        return (
            "generate"
            if state.get("knowledge_hits") or state.get("mcp_evidence")
            else "finish"
        )

    def _generate_reply(
        self,
        state: CustomerSuggestionState,
    ) -> dict[str, Any]:
        self._emit_stage("正在组织回复")
        employee = state["employee"]
        ticket = state["ticket"]
        hits = state.get("knowledge_hits", [])
        fast_draft = _technical_documentation_draft(state)
        if fast_draft is None:
            fast_draft = _technical_knowledge_draft(state)
        if fast_draft is None:
            fast_draft = _operational_knowledge_draft(state)
        if fast_draft is None:
            fast_draft = _technical_evidence_missing_draft(state)
        if fast_draft is not None:
            return {
                "draft": fast_draft,
                "trace": [
                    *state.get("trace", []),
                    (
                        "generate_reply → 确定性工具结果整理"
                        if fast_draft.provider == "mcp_fast_path"
                        else "generate_reply → 抽取式 RAG 回答"
                    ),
                ],
            }
        call, _, _ = self.tool_execution.begin(
            employee=employee,
            tool_key="draft.create",
            payload={
                "ticket_id": str(ticket.id),
                "text": "Generating a LangGraph reply suggestion",
                "citation_count": len(hits),
                "claim_count": 1,
            },
            correlation_id=state["usage_guard"].correlation_id,
            ticket_id=ticket.id,
        )
        routing = RoutingDecision(
            queue_id=ticket.queue_id or "MANUAL_TRIAGE",
            priority=Priority(ticket.priority or Priority.P2),
            needs_human=ticket.needs_human,
            human_reason=ticket.human_reason,
            matched_rule_id="LANGGRAPH_REPLY_SUGGESTION",
            reason_codes=[],
        )
        draft = build_draft_service_for_employee(
            employee,
            usage_guard=state["usage_guard"],
        ).generate(
            subject=ticket.subject,
            body=ticket.body,
            analysis=self._analysis(ticket),
            routing=routing,
            knowledge_hits=hits,
            skill_instructions=state.get("skill_instructions"),
            external_evidence=state.get("mcp_evidence", []),
            on_text_delta=self._on_text_delta,
        )
        self.tool_execution.succeed(
            call,
            {
                "citation_count": len(draft.citations),
                "claim_count": len(draft.claims),
                "provider": draft.provider,
                "model": draft.model,
                "fallback_used": draft.fallback_used,
            },
        )
        return {
            "draft": draft,
            "trace": [
                *state.get("trace", []),
                f"generate_reply → {draft.provider}/{draft.model}",
            ],
        }

    def _query(self, conversation_id: UUID) -> str:
        messages = list(
            self.session.scalars(
                select(CustomerMessage)
                .where(CustomerMessage.conversation_id == conversation_id)
                .order_by(CustomerMessage.sequence.desc())
                .limit(8)
            ).all()
        )
        return "\n".join(
            f"{'买家' if message.role == 'BUYER' else '客服'}："
            f"{message.content}"
            for message in reversed(messages)
        )

    def _analysis(self, ticket: Ticket) -> AnalysisResult:
        return AnalysisResult(
            category_primary=ticket.category_primary or "other_unclassified",
            category_secondary=ticket.category_secondary or "unknown",
            confidence=ticket.confidence or 0.0,
            risk_level=RiskLevel(ticket.risk_level or RiskLevel.R1),
            risk_tags=[],
            reason_codes=[],
            summary=ticket.summary or ticket.subject,
            needs_human=ticket.needs_human,
            human_reason=ticket.human_reason,
            model_provider="existing_analysis",
            model_name="ticket_analysis",
            fallback_used=False,
        )


def _technical_documentation_plan(
    query: str,
    available: list[McpToolTarget],
    *,
    context_repository: str | None = None,
) -> ToolPlan | None:
    if not _is_technical_documentation_question(query):
        return None
    repository = _resolved_repository(
        query,
        context_repository,
    )
    if repository is None:
        return None
    question = _latest_buyer_question(query)
    if _requires_deepwiki_answer(question):
        contents_target = next(
            (
                item
                for item in available
                if item.tool_name == "read_wiki_contents"
                and not item.is_write
            ),
            None,
        )
        if contents_target is not None:
            return ToolPlan(
                tool_id=contents_target.tool_id,
                arguments={"repoName": repository},
                reason="公开仓库模块与依赖问题使用确定性只读文档工具",
            )
        question_target = next(
            (
                item
                for item in available
                if item.tool_name == "ask_wiki_question"
                and not item.is_write
            ),
            None,
        )
        if question_target is not None:
            return ToolPlan(
                tool_id=question_target.tool_id,
                arguments={
                    "repoName": repository,
                    "question": question,
                },
                reason="公开仓库模块与依赖问题使用确定性只读问答工具",
            )
    target = next(
        (
            item
            for item in available
            if item.tool_name == "read_wiki_structure" and not item.is_write
        ),
        None,
    )
    if target is None:
        return None
    return ToolPlan(
        tool_id=target.tool_id,
        arguments={"repoName": repository},
        reason="公开仓库文档结构查询使用确定性只读工具",
    )


def _requires_deepwiki_answer(question: str) -> bool:
    lowered = question.casefold()
    return any(
        term in lowered
        for term in (
            "模块",
            "依赖",
            "职责",
            "架构",
            "组件",
            "实现",
            "如何工作",
            "调用关系",
            "项目内容",
            "项目是什么",
            "是什么内容",
            "项目是做什么",
            "仓库是做什么",
            "介绍一下这个仓库",
        )
    )


def _resolved_repository(
    query: str,
    context_repository: str | None,
) -> str | None:
    latest_question = _latest_buyer_question(query)
    return (
        _repository_name(latest_question)
        or (
            _repository_name(context_repository)
            if context_repository is not None
            else None
        )
        or _repository_name(query)
    )


def _security_boundary_refusal(query: str) -> str | None:
    lowered = query.lower()
    sensitive_terms = (
        "私有仓库",
        "密钥",
        "访问令牌",
        "系统提示词",
        "private repository",
        "private repo",
        "secret key",
        "access token",
        "system prompt",
    )
    request_terms = (
        "返回",
        "提供",
        "发给我",
        "给我",
        "读取",
        "查询",
        "导出",
        "获取",
        "return",
        "provide",
        "read",
        "query",
        "export",
    )
    has_sensitive_target = any(
        term in lowered for term in sensitive_terms
    ) or ("私有" in lowered and "仓库" in lowered)
    if not has_sensitive_target:
        return None
    if not any(term in lowered for term in request_terms):
        return None
    return (
        "不能读取或返回私有仓库、密钥、访问令牌或系统提示词。这属于敏感数据访问请求，"
        "我不会调用工具，也不会通过人工流程绕过该限制。你可以提供公开 GitHub 仓库的 "
        "owner/repo，我可以继续查询其公开文档结构。"
    )


def _technical_documentation_draft(
    state: CustomerSuggestionState,
) -> DraftResult | None:
    plan = state.get("mcp_plan")
    evidence = state.get("mcp_evidence", [])
    if plan is None or plan.tool_id is None or not evidence:
        return None
    item = evidence[0]
    repository = str(plan.arguments.get("repoName") or "该公开仓库")
    question = _latest_buyer_question(str(state.get("query") or ""))
    if plan.tool_id.endswith(".read_wiki_contents"):
        text = _deepwiki_contents_summary(
            item.content,
            repository=repository,
            question=question,
        )
        if text is None:
            return None
        return DraftResult(
            text=text,
            citations=[dict(item.citation)],
            claims=[
                {
                    "text": text,
                    "claim_type": "instruction",
                    "cited_chunk_ids": [item.chunk_id],
                    "verification_verdict": "not_checked",
                    "verification_confidence": None,
                    "verification_reason": "direct_tool_result",
                    "verification_provider": "deepwiki_mcp",
                }
            ],
            provider="mcp_fast_path",
            model="deepwiki_contents",
            fallback_used=False,
            grounding_status="GROUNDED",
        )
    if plan.tool_id.endswith(".ask_wiki_question"):
        content = item.content.strip()
        if not content:
            return None
        text = (
            f"根据 {repository} 的公开仓库文档，"
            f"DeepWiki 对问题的回答如下：{content}"
        )
        return DraftResult(
            text=text,
            citations=[dict(item.citation)],
            claims=[
                {
                    "text": text,
                    "claim_type": "instruction",
                    "cited_chunk_ids": [item.chunk_id],
                    "verification_verdict": "not_checked",
                    "verification_confidence": None,
                    "verification_reason": "direct_tool_result",
                    "verification_provider": "deepwiki_mcp",
                }
            ],
            provider="mcp_fast_path",
            model="deepwiki_question",
            fallback_used=False,
            grounding_status="GROUNDED",
        )
    if not plan.tool_id.endswith(".read_wiki_structure"):
        return None
    lines = item.content.splitlines()
    sections = [
        line.removeprefix("- ").strip()
        for line in lines
        if line.startswith("- ")
    ]
    if not sections:
        return None
    matched_section = _matched_wiki_section(question, sections)
    if matched_section is None:
        text = (
            f"已查询 {repository} 的公开仓库文档结构，共 {len(sections)} 个主章节："
            + "、".join(sections)
            + "。以上内容来自 DeepWiki 实时只读工具结果。"
        )
    else:
        start = next(
            index
            for index, line in enumerate(lines)
            if line.removeprefix("- ").strip() == matched_section
        )
        details = [matched_section]
        for line in lines[start + 1 :]:
            if line.startswith("- "):
                break
            compact = line.strip().removeprefix("- ").strip()
            if compact:
                details.append(compact)
        text = (
            f"根据 {repository} 的公开仓库文档，"
            f"“{matched_section}”包含："
            + "；".join(details[1:])
            + "。以上内容来自 DeepWiki 实时只读工具结果。"
        )
    return DraftResult(
        text=text,
        citations=[dict(item.citation)],
        claims=[
            {
                "text": text,
                "claim_type": "instruction",
                "cited_chunk_ids": [item.chunk_id],
                "verification_verdict": "not_checked",
                "verification_confidence": None,
                "verification_reason": "direct_tool_result",
                "verification_provider": "deepwiki_mcp",
            }
        ],
        provider="mcp_fast_path",
        model="deepwiki_tool_result",
        fallback_used=False,
        grounding_status="GROUNDED",
    )


def _technical_knowledge_draft(
    state: CustomerSuggestionState,
) -> DraftResult | None:
    hits = state.get("knowledge_hits", [])
    if (
        state.get("skill") != "developer-repository-support"
        or not hits
        or _resolved_repository(
            str(state.get("query") or ""),
            state.get("repository"),
        )
        is not None
    ):
        return None
    hit = hits[0]
    content = hit.content.strip()
    if not content:
        return None
    question = _latest_buyer_question(str(state.get("query") or ""))
    extracted = _extract_relevant_knowledge_sentences(content, question)
    text = f"根据已发布知识《{hit.title}》：{extracted}"
    return DraftResult(
        text=text,
        citations=[
            {
                "chunk_id": str(hit.chunk_id),
                "document_id": str(hit.document_id),
                "space_id": str(hit.space_id) if hit.space_id else None,
                "title": hit.title,
                "version": hit.version,
            }
        ],
        claims=[
            {
                "text": text,
                "claim_type": "policy",
                "cited_chunk_ids": [str(hit.chunk_id)],
                "verification_verdict": "not_checked",
                "verification_confidence": None,
                "verification_reason": "direct_knowledge_extract",
                "verification_provider": "rag",
            }
        ],
        provider="rag_fast_path",
        model="knowledge_extract",
        fallback_used=False,
        grounding_status="GROUNDED",
    )


def _operational_knowledge_draft(
    state: CustomerSuggestionState,
) -> DraftResult | None:
    ticket = state.get("ticket")
    hits = state.get("knowledge_hits", [])
    if (
        ticket is None
        or not hits
        or ticket.category_primary
        not in {
            "product_howto",
            "access_identity",
            "service_incident",
            "billing_invoice",
        }
        or _is_technical_documentation_question(state["query"])
    ):
        return None
    hit = hits[0]
    content = hit.content.strip()
    if not content:
        return None
    question = _latest_buyer_question(str(state.get("query") or ""))
    extracted = _extract_relevant_knowledge_sentences(content, question)
    text = f"根据已发布知识《{hit.title}》：{extracted}"
    return DraftResult(
        text=text,
        citations=[
            {
                "chunk_id": str(hit.chunk_id),
                "document_id": str(hit.document_id),
                "space_id": str(hit.space_id) if hit.space_id else None,
                "title": hit.title,
                "version": hit.version,
            }
        ],
        claims=[
            {
                "text": text,
                "claim_type": "instruction",
                "cited_chunk_ids": [str(hit.chunk_id)],
                "verification_verdict": "not_checked",
                "verification_confidence": None,
                "verification_reason": "direct_knowledge_extract",
                "verification_provider": "rag",
            }
        ],
        provider="rag_fast_path",
        model="knowledge_extract",
        fallback_used=False,
        grounding_status="GROUNDED",
    )


def _technical_evidence_missing_draft(
    state: CustomerSuggestionState,
) -> DraftResult | None:
    query = str(state.get("query") or "")
    repository = _resolved_repository(
        query,
        state.get("repository"),
    )
    if (
        not _is_technical_documentation_question(query)
        and repository is None
    ):
        return None
    failed_tools = [
        item
        for item in state.get("mcp_tool_calls", [])
        if item.status == "FAILED"
    ]
    if repository is not None and failed_tools:
        failed_tool_names = "、".join(
            dict.fromkeys(item.tool_id for item in failed_tools)
        )
        text = (
            f"我已识别公开仓库 {repository}，但只读文档工具 "
            f"{failed_tool_names} 返回读取失败。"
            "因此当前无法确认该仓库的项目内容、目录或模块关系。"
            "这通常表示仓库尚未被 DeepWiki 收录、仓库不可公开访问，"
            "或外部工具暂时不可用。请确认仓库可公开访问后重试，"
            "不要仅凭仓库名称推测内容。"
        )
    elif repository is not None:
        text = (
            f"我已识别为公开仓库文档查询：{repository}。"
            "但当前研发支持员工没有调用到可用的仓库文档工具，"
            "也没有检索到能支持当前问题的已发布资料，"
            "因此不能可靠回答。请检查 DeepWiki 只读 MCP 是否已绑定并可用，"
            "或补充该仓库的架构文档后再查询。"
        )
    else:
        text = (
            "我已识别为研发文档查询，但当前缺少可用于回答的公开仓库地址，"
            "也没有检索到能直接支持结论的已发布资料。"
            "请提供 owner/repo 格式的公开 GitHub 仓库和具体问题。"
        )
    return DraftResult(
        text=text,
        citations=[],
        claims=[],
        provider="system_policy",
        model="technical-evidence-gate-v1",
        fallback_used=False,
        grounding_status="NO_KNOWLEDGE",
    )


def _deepwiki_contents_summary(
    content: str,
    *,
    repository: str,
    question: str,
) -> str | None:
    text = _unwrap_mcp_content(content)
    if not text:
        return None
    architecture = _deepwiki_architecture_summary(text)
    purpose = (
        _deepwiki_purpose_summary(text)
        if _asks_about_project_content(question)
        else None
    )
    if purpose:
        sections = [f"项目目标与范围：{purpose}"]
        if architecture:
            sections.append(architecture)
        return (
            f"根据 {repository} 的公开仓库文档，"
            f"与“{question.rstrip('。？?')}”直接相关的信息如下：\n"
            + "\n\n".join(sections)
            + "\n以上内容来自 DeepWiki 实时只读文档结果。"
        )
    if architecture:
        return (
            f"根据 {repository} 的公开仓库文档，"
            f"与“{question.rstrip('。？?')}”直接相关的信息如下：\n"
            f"{architecture}\n"
            "以上内容来自 DeepWiki 实时只读文档结果。"
        )
    relevant = _deepwiki_relevant_excerpt(text, question)
    if not relevant:
        return None
    return (
        f"根据 {repository} 的公开仓库文档，"
        f"与问题相关的原文证据如下：{relevant}。"
        "以上内容来自 DeepWiki 实时只读文档结果。"
    )


def _asks_about_project_content(question: str) -> bool:
    lowered = question.casefold()
    return any(
        term in lowered
        for term in (
            "项目内容",
            "项目是什么",
            "是什么内容",
            "项目是做什么",
            "仓库是做什么",
            "介绍一下这个仓库",
        )
    )


def _deepwiki_purpose_summary(text: str) -> str | None:
    match = re.search(
        r"##\s+(?:Purpose and Scope|Overview)\s*(.*?)(?=\n##\s|$)",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if match is None:
        return None
    paragraphs = [
        " ".join(paragraph.split())
        for paragraph in re.split(r"\n\s*\n", match.group(1))
        if paragraph.strip()
        and not paragraph.lstrip().startswith(("```", "-", "[", "<"))
    ]
    if not paragraphs:
        return None
    return " ".join(paragraphs[:2])[:900]


def _unwrap_mcp_content(content: str) -> str:
    stripped = content.strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        result_match = re.search(
            r'"result"\s*:\s*("(?:\\.|[^"\\])*")',
            stripped,
            flags=re.DOTALL,
        )
        if result_match is not None:
            try:
                decoded = json.loads(result_match.group(1))
            except json.JSONDecodeError:
                decoded = None
            if isinstance(decoded, str):
                return decoded.strip()
        result_marker = re.search(
            r'"result"\s*:\s*"',
            stripped,
        )
        if result_marker is not None:
            truncated = stripped[result_marker.end():]
            if truncated.endswith('"\n}'):
                truncated = truncated[:-3]
            elif truncated.endswith('"}'):
                truncated = truncated[:-2]
            return (
                truncated.replace("\\r", "\r")
                .replace("\\n", "\n")
                .replace('\\"', '"')
                .replace("\\\\", "\\")
                .strip()
            )
        return stripped
    if isinstance(payload, dict):
        result = payload.get("result")
        if isinstance(result, str):
            return result.strip()
    return stripped


def _deepwiki_architecture_summary(text: str) -> str | None:
    graph_match = re.search(
        r"```mermaid\s*(.*?)```",
        text,
        flags=re.DOTALL,
    )
    if graph_match is None:
        return None
    graph = graph_match.group(1)
    node_pattern = re.compile(r'(\w+)\["([^"]+)"\]')
    node_labels = {
        node_id: label.split("<br/>", 1)[0].strip()
        for node_id, label in node_pattern.findall(graph)
    }
    if not node_labels:
        return None
    layer_translations = {
        "Server Layer": "服务端层",
        "Transport Layer": "传输层",
        "Client Layer": "客户端层",
        "Protocol Foundation": "协议基础层",
    }
    layer_matches = list(
        re.finditer(r'subgraph\s+"([^"]+)"', graph)
    )
    layers: list[str] = []
    for index, match in enumerate(layer_matches):
        section_start = match.end()
        section_end = (
            layer_matches[index + 1].start()
            if index + 1 < len(layer_matches)
            else len(graph)
        )
        section = graph[section_start:section_end]
        labels = [
            label.split("<br/>", 1)[0].strip()
            for _, label in node_pattern.findall(section)
        ]
        labels = list(dict.fromkeys(labels))
        if labels:
            layer_name = layer_translations.get(
                match.group(1),
                match.group(1),
            )
            layers.append(
                f"- {layer_name}：{'、'.join(labels[:6])}"
            )
    if not layers:
        return None
    edge_translations = {
        "delegates to": "委托给",
        "used by": "被使用于",
    }
    dependencies: list[str] = []
    for source, label, target in re.findall(
        r"(\w+)\s*-->\|([^|]+)\|\s*(\w+)",
        graph,
    ):
        source_name = node_labels.get(source)
        target_name = node_labels.get(target)
        if source_name is None or target_name is None:
            continue
        relation_label = label.strip().strip('"').strip()
        relation = edge_translations.get(
            relation_label,
            relation_label,
        )
        dependencies.append(
            f"- {source_name} {relation} {target_name}"
        )
    for source, target in re.findall(
        r"(\w+)\s*-->\s*(\w+)(?!\|)",
        graph,
    ):
        if source not in node_labels or target not in node_labels:
            continue
        dependencies.append(
            f"- {node_labels[source]} 依赖 {node_labels[target]}"
        )
    dependencies = list(dict.fromkeys(dependencies))[:8]
    lines = ["主要模块：", *layers]
    if dependencies:
        lines.extend(["", "关键依赖：", *dependencies])
    return "\n".join(lines)


def _deepwiki_relevant_excerpt(text: str, question: str) -> str | None:
    cleaned = re.sub(
        r"<details>.*?</details>",
        "",
        text,
        flags=re.DOTALL,
    )
    terms = [
        term
        for term in re.findall(r"[A-Za-z0-9_.-]{3,}|[\u4e00-\u9fff]{2,}", question)
        if term.casefold() not in {"主要", "模块", "依赖", "关系", "说明", "依据"}
    ]
    paragraphs = [
        " ".join(paragraph.split())
        for paragraph in re.split(r"\n\s*\n", cleaned)
        if len(paragraph.strip()) >= 40
        and not paragraph.lstrip().startswith(("```", "|", "#"))
    ]
    scored = sorted(
        (
            (
                sum(
                    1
                    for term in terms
                    if term.casefold() in paragraph.casefold()
                ),
                paragraph,
            )
            for paragraph in paragraphs
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    selected = [paragraph for score, paragraph in scored if score > 0][:2]
    if not selected:
        selected = [paragraph for _, paragraph in scored[:2]]
    if not selected:
        return None
    return "；".join(item[:600] for item in selected)[:1200]


def _technical_knowledge_hit_matches(
    hit: KnowledgeHit,
    query: str,
) -> bool:
    text = f"{hit.title}\n{hit.content}".casefold()
    repository = _repository_name(query)
    if repository is not None and repository.casefold() in text:
        return True
    return any(
        term in text
        for term in (
            "github",
            "gitlab",
            "仓库",
            "代码",
            "模块",
            "依赖",
            "mcp",
            "sdk",
            "接口",
            "研发",
            "开发文档",
            "架构",
        )
    )


def _extract_relevant_knowledge_sentences(
    content: str,
    question: str,
) -> str:
    segments = [
        segment.strip()
        for segment in re.split(r"[。；\n]+", content)
        if segment.strip()
    ]
    lowered_question = question.lower()
    indicators = (
        "安全限制",
        "私有仓库",
        "密钥",
        "访问令牌",
        "系统提示词",
        "客户数据",
        "内部代码",
        "工具失败",
        "仓库不存在",
        "公开文档范围",
        "转人工",
        "只读工具",
    )
    question_indicators = [
        term for term in indicators if term in lowered_question
    ]
    if "安全限制" in lowered_question:
        question_indicators.extend(
            ["私有仓库", "密钥", "客户数据", "内部代码"]
        )
    if not question_indicators:
        return content[:800]
    selected = [
        segment
        for segment in segments
        if any(term in segment for term in question_indicators)
    ]
    if not selected:
        selected = [
            segment
            for segment in segments
            if any(term in segment for term in indicators)
        ][:3]
    return "；".join(selected[:3]) or content[:800]


def _latest_buyer_question(query: str) -> str:
    if "买家：" not in query:
        return query.strip()
    latest = query.rsplit("买家：", 1)[-1]
    # Replies rendered after the buyer turn are assistant text, not the
    # question being routed or checked.
    return latest.split("\n客服：", 1)[0].strip()


def _matched_wiki_section(
    question: str,
    sections: list[str],
) -> str | None:
    lowered = question.lower()
    aliases = {
        "客户端": "Client Framework",
        "传输": "Transport Layer",
        "streamable http": "Transport Layer",
        "协议": "Protocol & Types System",
        "认证": "Server-Side Authentication",
        "示例": "Examples & Tutorials",
        "部署": "Deployment & Integration",
        "迁移": "Migration & API Changes",
    }
    for section in sections:
        title = re.sub(r"^\d+(?:\.\d+)*\s+", "", section)
        if title.lower() in lowered:
            return section
    for keyword, title in aliases.items():
        if keyword in question:
            match = next(
                (section for section in sections if title in section),
                None,
            )
            if match is not None:
                return match
    return None

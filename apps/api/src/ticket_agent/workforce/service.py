from __future__ import annotations

import builtins
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ticket_agent.agent_skills.service import AgentSkillService
from ticket_agent.digital_employees.models import (
    DigitalEmployee,
    DigitalEmployeeRouteDecision,
)
from ticket_agent.digital_employees.router_service import DigitalEmployeeRouter
from ticket_agent.digital_employees.service import (
    EMPLOYEE_TEMPLATES,
    DigitalEmployeeService,
    EmployeeTemplate,
)
from ticket_agent.knowledge.embedding_factory import get_embedding_provider
from ticket_agent.knowledge.service import KnowledgeHit, KnowledgeService
from ticket_agent.mcp_connectors.runtime import McpToolRuntime
from ticket_agent.model_gateway.profile import (
    build_reranker_for_employee,
    build_tool_planner_for_employee,
    build_workforce_gateway_for_employee,
)
from ticket_agent.model_gateway.types import DraftSnippet, ModelGatewayError
from ticket_agent.model_gateway.usage import ModelUsageGuard
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.workflow.profile import resolve_knowledge_options
from ticket_agent.workforce.models import WorkforceTask, WorkforceTaskStep
from ticket_agent.workforce.schemas import (
    WorkforceTaskCreate,
    WorkforceTaskList,
    WorkforceTaskStepView,
    WorkforceTaskView,
)


class WorkforceTaskService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def plan(
        self,
        payload: WorkforceTaskCreate,
        *,
        actor_id: str,
    ) -> WorkforceTask:
        employee_service = DigitalEmployeeService(self.session)
        supervisor = (
            employee_service.get(payload.supervisor_employee_id)
            if payload.supervisor_employee_id
            else next(
                (
                    employee
                    for employee in employee_service.list_employees(
                        payload.business_unit_id
                    )
                    if employee.template_code
                    == "customer_service_supervisor"
                    and employee.status == "ACTIVE"
                ),
                None,
            )
        )
        if supervisor is not None:
            if supervisor.business_unit_id != payload.business_unit_id:
                raise ApiProblem(
                    status_code=422,
                    code="WORKFORCE_SUPERVISOR_UNIT_MISMATCH",
                    title="Supervisor belongs to another business unit",
                    detail=(
                        "The selected supervisor and workforce task must "
                        "share a business unit."
                    ),
                )
            if supervisor.status != "ACTIVE":
                raise ApiProblem(
                    status_code=409,
                    code="WORKFORCE_SUPERVISOR_NOT_ACTIVE",
                    title="Supervisor is not active",
                    detail=(
                        f"Supervisor status is {supervisor.status}; "
                        "select an active digital employee."
                    ),
                )
            if not _can_supervise(supervisor):
                raise ApiProblem(
                    status_code=422,
                    code="WORKFORCE_SUPERVISOR_CAPABILITY_REQUIRED",
                    title="Supervisor capability required",
                    detail=(
                        "The selected employee does not declare task "
                        "decomposition and coordination capabilities."
                    ),
                )
        task = WorkforceTask(
            business_unit_id=payload.business_unit_id,
            title=payload.title,
            objective=payload.objective,
            context_json=payload.context,
            supervisor_employee_id=supervisor.id if supervisor else None,
            status="PLAN_READY",
            created_by=actor_id,
        )
        self.session.add(task)
        self.session.flush()
        router = DigitalEmployeeRouter(self.session)
        steps: list[WorkforceTaskStep] = []
        for sequence, spec in enumerate(
            _task_steps(payload.objective),
            start=1,
        ):
            route = router.route_text(
                business_unit_id=payload.business_unit_id,
                subject=f"{spec.title} · {spec.required_capability}",
                body=_workforce_step_route_body(
                    task,
                    spec.title,
                    spec.instructions,
                ),
                channel="workforce",
            )
            step = WorkforceTaskStep(
                task_id=task.id,
                sequence=sequence,
                title=spec.title,
                instructions=spec.instructions,
                assigned_employee_id=route.employee.id,
                assigned_employee_key=route.employee.employee_key,
                route_decision_id=(
                    route.decision.id if route.decision else None
                ),
                status="PENDING",
            )
            self.session.add(step)
            steps.append(step)
        self.session.flush()
        task.capability_snapshot_json = self._capability_assessment(
            task,
            steps,
        )
        task.capability_assessed_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(task)
        return task

    def get(self, task_id: UUID) -> WorkforceTask:
        task = self.session.get(WorkforceTask, task_id)
        if task is None:
            raise ApiProblem(
                status_code=404,
                code="WORKFORCE_TASK_NOT_FOUND",
                title="Workforce task not found",
                detail=f"Workforce task {task_id} does not exist.",
            )
        return task

    def execute(
        self,
        task_id: UUID,
        *,
        correlation_id: str,
    ) -> None:
        task = self._get_for_update(task_id)
        if task.status in {"COMPLETED", "RUNNING"}:
            return
        if task.status != "QUEUED":
            raise ApiProblem(
                status_code=409,
                code="WORKFORCE_TASK_NOT_QUEUED",
                title="Workforce task is not queued",
                detail=f"Task status is {task.status}.",
            )
        task.status = "RUNNING"
        self.session.commit()
        steps = list(
            self.session.scalars(
                select(WorkforceTaskStep)
                .where(WorkforceTaskStep.task_id == task.id)
                .order_by(WorkforceTaskStep.sequence)
            ).all()
        )
        for step in steps:
            if step.status == "SUCCEEDED":
                continue
            step.status = "RUNNING"
            step.error_message = None
            self.session.commit()
            try:
                employee = DigitalEmployeeService(self.session).get(
                    step.assigned_employee_id
                )
                usage_guard = ModelUsageGuard(
                    self.session,
                    employee=employee,
                    ticket_id=None,
                    correlation_id=f"wf:{step.id}",
                )
                skills = AgentSkillService(
                    self.session
                ).resolve_employee_skills(
                    employee.id,
                    employee.business_unit_id,
                )
                skill_instructions = "\n".join(
                    f"{skill.name}: {skill.instructions}"
                    for skill in skills[:3]
                )
                options = resolve_knowledge_options(employee)
                scope = employee.knowledge_policy_json.get(
                    "default_scope",
                    {},
                )
                hits = KnowledgeService(
                    self.session,
                    embedding_provider=get_embedding_provider(usage_guard),
                    reranker=build_reranker_for_employee(
                        employee,
                        usage_guard=usage_guard,
                    ),
                ).search(
                    query=(
                        f"{task.objective}\n{step.title}\n"
                        f"{step.instructions}"
                    ),
                    business_unit_id=employee.business_unit_id,
                    employee_id=employee.id,
                    scope={
                        str(key): str(value)
                        for key, value in scope.items()
                        if isinstance(value, str)
                    },
                    top_k=options.top_k,
                    min_score=options.min_score,
                )
                snippets = [
                    _snippet_from_hit(hit) for hit in hits[:5]
                ]
                upstream_snippets = _upstream_step_snippets(
                    steps,
                    before_sequence=step.sequence,
                )
                snippets.extend(upstream_snippets)
                tool_snippets, tool_calls = self._execute_read_tools(
                    employee=employee,
                    task=task,
                    step=step,
                    skill_instructions=skill_instructions,
                    usage_guard=usage_guard,
                )
                snippets.extend(tool_snippets)
                response = build_workforce_gateway_for_employee(
                    employee,
                    usage_guard=usage_guard,
                ).generate_workforce_step(
                    task_title=task.title,
                    objective=task.objective,
                    context=task.context_json,
                    step_title=step.title,
                    instructions=step.instructions,
                    snippets=snippets,
                    skill_instructions=skill_instructions,
                )
                step.output_json = {
                    "summary": response.output.summary,
                    "findings": response.output.findings,
                    "recommended_actions": response.output.recommended_actions,
                    "requires_human": response.output.requires_human,
                    "citations": [
                        {
                            "chunk_id": hit.chunk_id,
                            "title": hit.title,
                            "version": hit.version,
                        }
                        for hit in hits
                        if str(hit.chunk_id)
                        in response.output.cited_chunk_ids
                    ]
                    + [
                        {
                            "chunk_id": snippet.chunk_id,
                            "title": snippet.title,
                            "version": snippet.version,
                            "source_type": "mcp",
                        }
                        for snippet in tool_snippets
                        if snippet.chunk_id
                        in response.output.cited_chunk_ids
                    ]
                    + [
                        {
                            "chunk_id": snippet.chunk_id,
                            "title": snippet.title,
                            "version": snippet.version,
                            "source_type": "workflow_step",
                        }
                        for snippet in upstream_snippets
                    ],
                    "provider": response.provider,
                    "model": response.model,
                    "fallback_used": response.fallback_used,
                    "tool_calls": tool_calls,
                }
                step.status = "SUCCEEDED"
                step.completed_at = datetime.now(UTC)
                self.session.commit()
            except Exception as exc:
                step_id = step.id
                self.session.rollback()
                failed_step = self.session.get(WorkforceTaskStep, step_id)
                failed_task = self.session.get(WorkforceTask, task_id)
                if failed_step is None or failed_task is None:
                    return
                failed_step.status = "FAILED"
                failed_step.error_message = (
                    f"{type(exc).__name__}: {exc}"
                )[:2000]
                failed_step.completed_at = datetime.now(UTC)
                failed_task.status = "NEEDS_REVIEW"
                self.session.commit()

        self.session.refresh(task)
        steps = list(
            self.session.scalars(
                select(WorkforceTaskStep)
                .where(WorkforceTaskStep.task_id == task.id)
                .order_by(WorkforceTaskStep.sequence)
            ).all()
        )
        summaries = [
            str(step.output_json.get("summary", ""))
            for step in steps
            if step.output_json.get("summary")
        ]
        task.result_summary = "\n".join(
            f"{step.sequence}. {step.title}: "
            f"{step.output_json.get('summary', step.error_message or '无结果')}"
            for step in steps
        )
        requires_human = any(
            step.status == "FAILED"
            or bool(step.output_json.get("requires_human"))
            for step in steps
        )
        task.status = "NEEDS_REVIEW" if requires_human else "COMPLETED"
        if not summaries and not task.result_summary:
            task.result_summary = "No workforce step produced a result."
        self.session.commit()

    def queue_execution(
        self,
        task_id: UUID,
    ) -> tuple[WorkforceTask, bool]:
        task = self._get_for_update(task_id)
        if task.status in {"COMPLETED", "RUNNING", "QUEUED"}:
            return task, False
        if task.status != "PLAN_READY":
            raise ApiProblem(
                status_code=409,
                code="WORKFORCE_RETRY_REQUIRED",
                title="Workforce retry required",
                detail=(
                    "Only a PLAN_READY task can be queued. Reset failed "
                    "steps before executing a task in review."
                ),
            )
        steps = self._task_steps_for_update(task.id)
        self._reroute_pending_steps(task, steps)
        assessment = self._capability_assessment(task, steps)
        task.capability_snapshot_json = assessment
        task.capability_assessed_at = datetime.now(UTC)
        raw_gaps = assessment.get("gaps", [])
        gaps = raw_gaps if isinstance(raw_gaps, list) else []
        raw_readiness = assessment.get("employee_readiness", [])
        readiness = (
            raw_readiness if isinstance(raw_readiness, list) else []
        )
        if gaps:
            self.session.commit()
            missing = "、".join(
                dict.fromkeys(
                    str(gap["required_capability"])
                    for gap in gaps
                    if isinstance(gap, dict)
                )
            )
            raise ApiProblem(
                status_code=409,
                code="WORKFORCE_CAPABILITY_GAP",
                title="Workforce capability gap",
                detail=(
                    f"缺少执行能力：{missing}。"
                    "请先审核并创建缺失的数字员工。"
                ),
            )
        blocked = [
            employee
            for employee in readiness
            if isinstance(employee, dict)
            and employee.get("status") == "BLOCKED"
        ]
        if blocked:
            self.session.commit()
            names = "、".join(
                dict.fromkeys(
                    str(employee.get("employee_name"))
                    for employee in blocked
                )
            )
            raise ApiProblem(
                status_code=409,
                code="WORKFORCE_EMPLOYEE_NOT_READY",
                title="Digital employee not ready",
                detail=f"以下数字员工未满足执行条件：{names}。",
            )
        task.status = "QUEUED"
        self.session.commit()
        self.session.refresh(task)
        return task, True

    def reassess(self, task_id: UUID) -> WorkforceTask:
        task = self._get_for_update(task_id)
        if task.status not in {"PLAN_READY", "NEEDS_REVIEW"}:
            raise ApiProblem(
                status_code=409,
                code="WORKFORCE_TASK_NOT_REASSESSABLE",
                title="Workforce task cannot be reassessed",
                detail=f"Task status is {task.status}.",
            )
        steps = self._task_steps_for_update(task.id)
        self._reroute_pending_steps(task, steps)
        task.capability_snapshot_json = self._capability_assessment(
            task,
            steps,
        )
        task.capability_assessed_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(task)
        return task

    def _execute_read_tools(
        self,
        *,
        employee: DigitalEmployee,
        task: WorkforceTask,
        step: WorkforceTaskStep,
        skill_instructions: str,
        usage_guard: ModelUsageGuard,
    ) -> tuple[list[DraftSnippet], list[dict[str, object]]]:
        runtime = McpToolRuntime(self.session)
        available = [
            target
            for target in runtime.available_tools(employee)
            if not target.is_write
        ]
        if not available:
            return [], []
        planner = build_tool_planner_for_employee(
            employee,
            usage_guard=usage_guard,
        )
        if planner is None:
            return [], []
        try:
            plan = planner.plan_tool(
                query=(
                    f"任务：{task.title}\n目标：{task.objective}\n"
                    f"上下文：{json.dumps(task.context_json, ensure_ascii=False)}\n"
                    f"步骤：{step.title}\n要求：{step.instructions}"
                ),
                subject=step.title,
                skill_name="专业子任务",
                skill_instructions=skill_instructions,
                tools=[target.spec for target in available],
            )
        except (ModelGatewayError, ValueError) as exc:
            return [], [
                {
                    "status": "PLANNING_FAILED",
                    "error_code": "TOOL_PLANNING_FAILED",
                    "error_message": str(exc)[:500],
                }
            ]
        if plan.tool_id is None:
            return [], []
        result = runtime.execute(
            employee=employee,
            tool_id=plan.tool_id,
            arguments=plan.arguments,
            correlation_id=f"wf:{step.id}",
            ticket_id=None,
        )
        evidence = result.evidence
        snippets = (
            [
                DraftSnippet(
                    chunk_id=evidence.chunk_id,
                    title=evidence.title,
                    version=evidence.version,
                    content=evidence.content,
                )
            ]
            if evidence is not None
            else []
        )
        return snippets, [
            {
                "tool_id": result.tool_id,
                "status": result.status,
                "tool_call_id": str(result.tool_call_id),
                "duration_ms": result.duration_ms,
                "error_code": result.error_code,
                "error_message": result.error_message,
            }
        ]

    def retry_failed(self, task_id: UUID) -> WorkforceTask:
        task = self._get_for_update(task_id)
        if task.status != "NEEDS_REVIEW":
            raise ApiProblem(
                status_code=409,
                code="WORKFORCE_TASK_NOT_RETRYABLE",
                title="Workforce task is not retryable",
                detail=f"Task status is {task.status}.",
            )
        steps = list(
            self.session.scalars(
                select(WorkforceTaskStep).where(
                    WorkforceTaskStep.task_id == task.id,
                    WorkforceTaskStep.status.in_(("RUNNING", "FAILED")),
                )
            ).all()
        )
        if not steps:
            raise ApiProblem(
                status_code=409,
                code="WORKFORCE_NO_FAILED_STEPS",
                title="No failed steps to retry",
                detail="This task has no failed or interrupted steps.",
            )
        for step in steps:
            step.status = "PENDING"
            step.error_message = None
            step.completed_at = None
        task.status = "PLAN_READY"
        all_steps = list(
            self.session.scalars(
                select(WorkforceTaskStep)
                .where(WorkforceTaskStep.task_id == task.id)
                .order_by(WorkforceTaskStep.sequence)
            ).all()
        )
        self._reroute_pending_steps(task, all_steps)
        task.capability_snapshot_json = self._capability_assessment(
            task,
            all_steps,
        )
        task.capability_assessed_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(task)
        return task

    def _get_for_update(self, task_id: UUID) -> WorkforceTask:
        task = self.session.scalar(
            select(WorkforceTask)
            .where(WorkforceTask.id == task_id)
            .with_for_update()
        )
        if task is None:
            raise ApiProblem(
                status_code=404,
                code="WORKFORCE_TASK_NOT_FOUND",
                title="Workforce task not found",
                detail=f"Workforce task {task_id} does not exist.",
            )
        return task

    def _task_steps_for_update(
        self,
        task_id: UUID,
    ) -> list[WorkforceTaskStep]:
        return list(
            self.session.scalars(
                select(WorkforceTaskStep)
                .where(WorkforceTaskStep.task_id == task_id)
                .order_by(WorkforceTaskStep.sequence)
                .with_for_update()
            ).all()
        )

    def _reroute_pending_steps(
        self,
        task: WorkforceTask,
        steps: list[WorkforceTaskStep],
    ) -> None:
        router = DigitalEmployeeRouter(self.session)
        specs = {
            spec.title: spec for spec in _task_steps(task.objective)
        }
        for step in steps:
            if step.status != "PENDING":
                continue
            spec = specs.get(step.title)
            route = router.route_text(
                business_unit_id=task.business_unit_id,
                subject=(
                    f"{step.title} · {spec.required_capability}"
                    if spec is not None
                    else f"{task.title} · {step.title}"
                ),
                body=(
                    _workforce_step_route_body(
                        task,
                        step.title,
                        step.instructions,
                    )
                ),
                channel="workforce",
            )
            step.assigned_employee_id = route.employee.id
            step.assigned_employee_key = route.employee.employee_key
            step.route_decision_id = (
                route.decision.id if route.decision else None
            )
        self.session.flush()

    def list(self, business_unit_id: str) -> WorkforceTaskList:
        total = self.session.scalar(
            select(func.count())
            .select_from(WorkforceTask)
            .where(WorkforceTask.business_unit_id == business_unit_id)
        ) or 0
        tasks = list(
            self.session.scalars(
                select(WorkforceTask)
                .where(WorkforceTask.business_unit_id == business_unit_id)
                .order_by(WorkforceTask.created_at.desc())
                .limit(100)
            ).all()
        )
        return WorkforceTaskList(
            items=[self.view(task) for task in tasks],
            total=int(total),
        )

    def _capability_assessment(
        self,
        task: WorkforceTask,
        steps: builtins.list[WorkforceTaskStep],
    ) -> dict[str, object]:
        employee_ids = {
            step.assigned_employee_id for step in steps
        }
        employees = {
            employee.id: employee
            for employee in self.session.scalars(
                select(DigitalEmployee).where(
                    DigitalEmployee.id.in_(employee_ids)
                )
            ).all()
        }
        active_employees = list(
            self.session.scalars(
                select(DigitalEmployee).where(
                    DigitalEmployee.business_unit_id
                    == task.business_unit_id,
                    DigitalEmployee.status == "ACTIVE",
                )
            ).all()
        )
        decision_ids = {
            step.route_decision_id
            for step in steps
            if step.route_decision_id is not None
        }
        decisions = {
            decision.id: decision
            for decision in self.session.scalars(
                select(DigitalEmployeeRouteDecision).where(
                    DigitalEmployeeRouteDecision.id.in_(decision_ids)
                )
            ).all()
        }
        gaps = _capability_gaps(
            task,
            steps,
            employees,
            decisions,
            active_employees,
        )
        readiness = _employee_readiness(
            self.session,
            task,
            steps,
            employees,
        )
        return {
            "schema_version": 1,
            "gaps": gaps,
            "employee_readiness": readiness,
        }

    def view(self, task: WorkforceTask) -> WorkforceTaskView:
        steps = list(
            self.session.scalars(
                select(WorkforceTaskStep)
                .where(WorkforceTaskStep.task_id == task.id)
                .order_by(WorkforceTaskStep.sequence)
            ).all()
        )
        employee_ids = {
            step.assigned_employee_id for step in steps
        }
        if task.supervisor_employee_id:
            employee_ids.add(task.supervisor_employee_id)
        employees = {
            employee.id: employee
            for employee in self.session.scalars(
                select(DigitalEmployee).where(
                    DigitalEmployee.id.in_(employee_ids)
                )
            ).all()
        }
        decision_ids = {
            step.route_decision_id
            for step in steps
            if step.route_decision_id is not None
        }
        decisions = {
            decision.id: decision
            for decision in self.session.scalars(
                select(DigitalEmployeeRouteDecision).where(
                    DigitalEmployeeRouteDecision.id.in_(decision_ids)
                )
            ).all()
        }
        specs = {
            spec.title: spec
            for spec in _task_steps(task.objective)
        }
        snapshot = task.capability_snapshot_json
        assessment = (
            snapshot
            if snapshot.get("schema_version") == 1
            else self._capability_assessment(task, steps)
        )
        return WorkforceTaskView(
            id=task.id,
            business_unit_id=task.business_unit_id,
            title=task.title,
            objective=task.objective,
            context=task.context_json,
            supervisor_employee_id=task.supervisor_employee_id,
            supervisor_employee_name=(
                employees[task.supervisor_employee_id].name
                if task.supervisor_employee_id
                and task.supervisor_employee_id in employees
                else None
            ),
            status=task.status,
            result_summary=task.result_summary,
            created_by=task.created_by,
            steps=[
                WorkforceTaskStepView(
                    id=step.id,
                    sequence=step.sequence,
                    title=step.title,
                    instructions=step.instructions,
                    assigned_employee_id=step.assigned_employee_id,
                    assigned_employee_key=step.assigned_employee_key,
                    assigned_employee_name=employees[
                        step.assigned_employee_id
                    ].name,
                    route_decision_id=step.route_decision_id,
                    required_capability=(
                        specs[step.title].required_capability
                        if step.title in specs
                        else None
                    ),
                    route_reason_code=(
                        decisions[step.route_decision_id].reason_code
                        if step.route_decision_id in decisions
                        else None
                    ),
                    route_reason=(
                        decisions[step.route_decision_id].reason
                        if step.route_decision_id in decisions
                        else None
                    ),
                    route_confidence=(
                        decisions[step.route_decision_id].confidence
                        if step.route_decision_id in decisions
                        else None
                    ),
                    route_candidates=(
                        decisions[step.route_decision_id].candidates_json
                        if step.route_decision_id in decisions
                        else []
                    ),
                    status=step.status,
                    output=step.output_json,
                    error_message=step.error_message,
                    created_at=step.created_at,
                    completed_at=step.completed_at,
                )
                for step in steps
            ],
            capability_gaps=assessment.get("gaps", []),
            employee_readiness=assessment.get(
                "employee_readiness",
                [],
            ),
            capability_assessed_at=task.capability_assessed_at,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )


@dataclass(frozen=True)
class _WorkforceStepSpec:
    title: str
    instructions: str
    required_capability: str
    required_terms: tuple[str, ...]
    suggested_template_code: str


def _task_steps(objective: str) -> list[_WorkforceStepSpec]:
    text = objective.lower()
    commerce_terms = (
        "退款",
        "退货",
        "物流",
        "破损",
        "售后",
        "投诉",
        "补发",
        "财务",
    )
    if (
        any(term in text for term in ("入职", "劳动合同", "入职材料", "hr"))
        and not any(term in text for term in commerce_terms)
    ):
        return [
            _WorkforceStepSpec(
                title="确认入职资料要求",
                instructions="识别岗位、地区和新员工需提交的必要资料。",
                required_capability="入职资料收集",
                required_terms=("入职", "资料"),
                suggested_template_code="hr_onboarding",
            ),
            _WorkforceStepSpec(
                title="检查缺失与合规",
                instructions="核对资料完整性、隐私要求和人工审核边界。",
                required_capability="材料完整性与合规检查",
                required_terms=("资料", "合规", "入职"),
                suggested_template_code="hr_onboarding",
            ),
            _WorkforceStepSpec(
                title="生成入职沟通草案",
                instructions="形成可交付的入职资料沟通内容，并标明需 HR 确认事项。",
                required_capability="HR 入职沟通",
                required_terms=("入职", "HR", "资料"),
                suggested_template_code="hr_onboarding",
            ),
        ]
    if any(
        term in text
        for term in ("退款", "退货", "物流", "破损", "售后", "投诉")
    ):
        return [
            _WorkforceStepSpec(
                title="识别客户主诉与关联业务",
                instructions="判断问题涉及售前、售后、物流、资金和风险环节。",
                required_capability="售后与风险识别",
                required_terms=("售后", "退款", "风险"),
                suggested_template_code="ecommerce_aftersales",
            ),
            _WorkforceStepSpec(
                title="查询专业事实",
                instructions="调用对应专家的知识、订单或物流能力核实事实。",
                required_capability="实时物流与订单事实核验",
                required_terms=("物流", "快递", "运单", "订单"),
                suggested_template_code="ecommerce_logistics",
            ),
            _WorkforceStepSpec(
                title="生成统一处理建议",
                instructions="汇总专业结论，形成对客回复和内部处理建议。",
                required_capability="跨专业任务协调与汇总",
                required_terms=("协调", "汇总", "复杂"),
                suggested_template_code="customer_service_supervisor",
            ),
            _WorkforceStepSpec(
                title="检查风险与审批",
                instructions="检查退款、补偿、敏感信息和高风险升级条件。",
                required_capability="退款与售后风险审批",
                required_terms=("退款", "售后", "风险"),
                suggested_template_code="ecommerce_aftersales",
            ),
        ]
    return [
        _WorkforceStepSpec(
            title="分析任务目标",
            instructions="识别任务类别、所需能力、输入和预期产出。",
            required_capability="复杂任务分析与拆解",
            required_terms=("复杂", "拆解", "协调"),
            suggested_template_code="customer_service_supervisor",
        ),
        _WorkforceStepSpec(
            title="生成执行建议",
            instructions="给出可执行步骤、负责岗位和人工确认点。",
            required_capability="跨岗位方案协调",
            required_terms=("协调", "汇总", "复杂"),
            suggested_template_code="customer_service_supervisor",
        ),
    ]


def _workforce_step_route_body(
    task: WorkforceTask,
    step_title: str,
    instructions: str,
) -> str:
    if step_title in {"分析任务目标", "生成执行建议"}:
        return (
            f"{task.title}\n{task.objective}\n"
            f"{step_title}\n{instructions}"
        )
    return f"{step_title}\n{instructions}"


def _snippet_from_hit(hit: KnowledgeHit) -> DraftSnippet:
    return DraftSnippet(
        chunk_id=str(hit.chunk_id),
        title=hit.title,
        version=hit.version,
        content=hit.content,
    )


def _upstream_step_snippets(
    steps: list[WorkforceTaskStep],
    *,
    before_sequence: int,
) -> list[DraftSnippet]:
    snippets: list[DraftSnippet] = []
    for step in steps:
        if (
            step.sequence >= before_sequence
            or step.status != "SUCCEEDED"
            or not step.output_json
        ):
            continue
        content = {
            "summary": step.output_json.get("summary", ""),
            "findings": step.output_json.get("findings", []),
            "recommended_actions": step.output_json.get(
                "recommended_actions",
                [],
            ),
            "requires_human": step.output_json.get(
                "requires_human",
                False,
            ),
            "citations": step.output_json.get("citations", []),
            "tool_calls": step.output_json.get("tool_calls", []),
        }
        snippets.append(
            DraftSnippet(
                chunk_id=f"workflow-step:{step.id}",
                title=(
                    f"前置步骤 {step.sequence} · {step.title}"
                ),
                version="current",
                content=json.dumps(
                    content,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        )
    return snippets


@dataclass(frozen=True)
class _RequestedCapabilityRequirement:
    label: str
    required_terms: tuple[str, ...]
    suggested_template_code: str | None
    domain: str
    workflow_key: str
    capabilities: tuple[str, ...]
    intents: tuple[str, ...]
    skills: tuple[str, ...]
    tools: tuple[str, ...]


def _capability_gaps(
    task: WorkforceTask,
    steps: list[WorkforceTaskStep],
    employees: dict[UUID, DigitalEmployee],
    decisions: dict[UUID, DigitalEmployeeRouteDecision],
    active_employees: list[DigitalEmployee],
) -> list[dict[str, object]]:
    specs = {
        spec.title: spec
        for spec in _task_steps(task.objective)
    }
    gaps: list[dict[str, object]] = []
    for step in steps:
        spec = specs.get(step.title)
        employee = employees.get(step.assigned_employee_id)
        if (
            spec is None
            or employee is None
            or _employee_covers_requirement(
                employee,
                required_terms=spec.required_terms,
                suggested_template_code=spec.suggested_template_code,
            )
        ):
            continue
        template = _employee_template(spec.suggested_template_code)
        if template is None:
            continue
        decision = (
            decisions.get(step.route_decision_id)
            if step.route_decision_id is not None
            else None
        )
        if decision is not None and decision.reason_code in {
            "FALLBACK",
            "NO_MATCH_DEFAULT",
        }:
            reason = (
                f"未找到覆盖“{spec.required_capability}”的活跃员工，"
                f"当前由兜底员工“{employee.name}”承担，"
                f"路由置信度 {decision.confidence:.2f}。"
            )
        else:
            reason = (
                f"当前负责人“{employee.name}”的 Manifest 未声明"
                f"“{spec.required_capability}”能力。"
            )
        gaps.append(
            {
                "step_id": str(step.id),
                "sequence": step.sequence,
                "step_title": step.title,
                "required_capability": spec.required_capability,
                "assigned_employee_name": employee.name,
                "reason": reason,
                "recommended_template_code": template.code,
                "recommended_template_name": template.name,
                "recommended_domain": template.domain,
                "recommended_workflow_key": template.workflow_key,
                "recommended_capabilities": template.capabilities,
                "recommended_intents": template.intents,
                "recommended_skills": template.skill_codes,
                "recommended_tools": template.tool_allowlist,
                "status": "DRAFT_ONLY",
                "approval_required": True,
            }
        )

    covered_capabilities = {
        str(gap["required_capability"])
        for gap in gaps
    }
    for requirement in _requested_capability_requirements(task.objective):
        if requirement.label in covered_capabilities or any(
            _employee_covers_requirement(
                employee,
                required_terms=requirement.required_terms,
                suggested_template_code=requirement.suggested_template_code,
            )
            for employee in active_employees
        ):
            continue
        template = (
            _employee_template(requirement.suggested_template_code)
            if requirement.suggested_template_code
            else None
        )
        gaps.append(
            {
                "step_id": None,
                "sequence": None,
                "step_title": "任务能力覆盖检查",
                "required_capability": requirement.label,
                "assigned_employee_name": "无可匹配员工",
                "reason": (
                    f"任务明确要求“{requirement.label}”，但当前没有"
                    "活跃数字员工的 Manifest 覆盖该能力。"
                ),
                "recommended_template_code": (
                    template.code if template is not None else None
                ),
                "recommended_template_name": (
                    template.name
                    if template is not None
                    else f"{requirement.label}数字员工"
                ),
                "recommended_domain": (
                    template.domain
                    if template is not None
                    else requirement.domain
                ),
                "recommended_workflow_key": (
                    template.workflow_key
                    if template is not None
                    else requirement.workflow_key
                ),
                "recommended_capabilities": (
                    template.capabilities
                    if template is not None
                    else list(requirement.capabilities)
                ),
                "recommended_intents": (
                    template.intents
                    if template is not None
                    else list(requirement.intents)
                ),
                "recommended_skills": (
                    template.skill_codes
                    if template is not None
                    else list(requirement.skills)
                ),
                "recommended_tools": (
                    template.tool_allowlist
                    if template is not None
                    else list(requirement.tools)
                ),
                "status": "DRAFT_ONLY",
                "approval_required": True,
            }
        )
        covered_capabilities.add(requirement.label)
    return gaps


def _employee_readiness(
    session: Session,
    task: WorkforceTask,
    steps: list[WorkforceTaskStep],
    employees: dict[UUID, DigitalEmployee],
) -> list[dict[str, object]]:
    employee_ids = list(employees)
    if not employee_ids:
        return []

    specs = {
        spec.title: spec
        for spec in _task_steps(task.objective)
    }
    employee_service = DigitalEmployeeService(session)
    readiness: list[dict[str, object]] = []
    for employee_id in employee_ids:
        employee = employees[employee_id]
        employee_steps = [
            step
            for step in steps
            if step.assigned_employee_id == employee_id
        ]
        needs_live_data = any(
            _step_needs_live_data(step, specs.get(step.title))
            for step in employee_steps
        )
        evaluation = employee_service.evaluate_resources(employee)
        raw_checks_value = evaluation.get("checks", [])
        raw_checks = (
            raw_checks_value
            if isinstance(raw_checks_value, list)
            else []
        )
        checks: list[dict[str, str]] = []
        for raw in raw_checks:
            if not isinstance(raw, dict):
                continue
            key = str(raw.get("key"))
            if key == "mcp" and not needs_live_data:
                checks.append(
                    {
                        "key": "mcp",
                        "label": "实时业务工具",
                        "status": "NOT_APPLICABLE",
                        "detail": "当前子任务未声明必须使用实时外部数据。",
                    }
                )
                continue
            passed = raw.get("status") == "PASSED"
            status = (
                "READY"
                if passed
                else (
                    "BLOCKED"
                    if key in {"employee", "tools"}
                    else "WARNING"
                )
            )
            checks.append(
                {
                    "key": "status" if key == "employee" else key,
                    "label": str(raw.get("label")),
                    "status": status,
                    "detail": str(raw.get("detail")),
                }
            )
        if not needs_live_data and not any(
            check["key"] == "mcp" for check in checks
        ):
            checks.append(
                {
                    "key": "mcp",
                    "label": "实时业务工具",
                    "status": "NOT_APPLICABLE",
                    "detail": "当前子任务未声明必须使用实时外部数据。",
                }
            )
        elif needs_live_data and not any(
            check["key"] == "mcp" for check in checks
        ):
            checks.append(
                {
                    "key": "mcp",
                    "label": "实时业务工具",
                    "status": "WARNING",
                    "detail": "任务需要实时数据，但员工未声明可用 MCP。",
                }
            )
        if any(
            check["status"] == "BLOCKED"
            for check in checks
        ):
            status = "BLOCKED"
        elif any(
            check["status"] == "WARNING"
            for check in checks
        ):
            status = "DEGRADED"
        else:
            status = "READY"
        readiness.append(
            {
                "employee_id": str(employee.id),
                "employee_key": employee.employee_key,
                "employee_name": employee.name,
                "template_code": employee.template_code,
                "step_sequences": [
                    step.sequence for step in employee_steps
                ],
                "status": status,
                "checks": checks,
            }
        )
    return readiness


def _step_needs_live_data(
    step: WorkforceTaskStep,
    spec: _WorkforceStepSpec | None,
) -> bool:
    text = (
        f"{step.title}\n"
        f"{spec.required_capability if spec else ''}"
    )
    return any(
        term in text
        for term in (
            "实时",
            "订单",
            "物流",
            "快递",
            "运单",
            "签收",
        )
    )


def _requested_capability_requirements(
    objective: str,
) -> list[_RequestedCapabilityRequirement]:
    pattern = re.compile(
        r"(?m)^\s*(?:[-*•]|\d+[.、])?\s*"
        r"([^\n:：]{2,40}能力)\s*[:：]\s*(.+)$"
    )
    requirements: list[_RequestedCapabilityRequirement] = []
    seen: set[str] = set()
    for match in pattern.finditer(objective):
        label = match.group(1).strip()
        if label in seen:
            continue
        seen.add(label)
        requirements.append(
            _capability_requirement(label)
        )
    return requirements


def _capability_requirement(
    label: str,
) -> _RequestedCapabilityRequirement:
    label_text = label.lower()
    if any(
        term in label_text
        for term in ("财务", "支付", "金额", "退款单", "审批流")
    ):
        return _RequestedCapabilityRequirement(
            label=label,
            required_terms=("财务", "支付", "金额", "退款单", "审批流"),
            suggested_template_code=None,
            domain="finance",
            workflow_key="customer_service_ticket_v1",
            capabilities=(label,),
            intents=("财务", "退款单", "金额", "审批"),
            skills=(),
            tools=("ticket.read", "knowledge.search", "draft.create"),
        )
    if any(
        term in label_text
        for term in ("仓储", "库存", "出库", "补发")
    ):
        return _RequestedCapabilityRequirement(
            label=label,
            required_terms=("仓储", "库存", "出库", "补发"),
            suggested_template_code=None,
            domain="ecommerce_operations",
            workflow_key="customer_service_ticket_v1",
            capabilities=(label,),
            intents=("仓储", "库存", "出库", "补发"),
            skills=(),
            tools=("ticket.read", "knowledge.search", "draft.create"),
        )
    if any(
        term in label_text
        for term in ("售后", "退货", "换货", "破损", "退款")
    ):
        template = _employee_template("ecommerce_aftersales")
        return _requirement_from_template(label, template)
    if any(
        term in label_text
        for term in ("物流", "快递", "运单", "签收")
    ):
        template = _employee_template("ecommerce_logistics")
        return _requirement_from_template(label, template)
    if any(
        term in label_text
        for term in ("客服沟通", "安抚", "话术", "进度同步")
    ):
        template = _employee_template("customer_service_supervisor")
        return _requirement_from_template(label, template)
    return _RequestedCapabilityRequirement(
        label=label,
        required_terms=(label,),
        suggested_template_code=None,
        domain="customer_service",
        workflow_key="customer_service_ticket_v1",
        capabilities=(label,),
        intents=(label.removesuffix("能力"),),
        skills=(),
        tools=("ticket.read", "knowledge.search", "draft.create"),
    )


def _requirement_from_template(
    label: str,
    template: EmployeeTemplate | None,
) -> _RequestedCapabilityRequirement:
    if template is None:
        return _RequestedCapabilityRequirement(
            label=label,
            required_terms=(label,),
            suggested_template_code=None,
            domain="customer_service",
            workflow_key="customer_service_ticket_v1",
            capabilities=(label,),
            intents=(label.removesuffix("能力"),),
            skills=(),
            tools=("ticket.read", "knowledge.search", "draft.create"),
        )
    return _RequestedCapabilityRequirement(
        label=label,
        required_terms=(label,),
        suggested_template_code=template.code,
        domain=template.domain,
        workflow_key=template.workflow_key,
        capabilities=tuple(template.capabilities),
        intents=tuple(template.intents),
        skills=tuple(template.skill_codes),
        tools=tuple(template.tool_allowlist),
    )


def _employee_covers_requirement(
    employee: DigitalEmployee,
    *,
    required_terms: tuple[str, ...],
    suggested_template_code: str | None,
) -> bool:
    if (
        suggested_template_code is not None
        and employee.template_code == suggested_template_code
    ):
        return True
    values: list[str] = []
    for key in ("capabilities", "intents"):
        raw = employee.manifest_json.get(key, [])
        if isinstance(raw, list):
            values.extend(str(value) for value in raw)
    manifest_text = " ".join(values).lower()
    return any(
        term.lower() in manifest_text
        for term in required_terms
    )


def _can_supervise(employee: DigitalEmployee) -> bool:
    if employee.template_code == "customer_service_supervisor":
        return True
    capabilities = employee.manifest_json.get("capabilities", [])
    if not isinstance(capabilities, list):
        return False
    text = " ".join(str(value) for value in capabilities)
    return any(
        term in text
        for term in ("复杂任务拆解", "专业员工协调", "任务协调", "跨岗位协调")
    )


def _employee_template(
    code: str | None,
) -> EmployeeTemplate | None:
    if code is None:
        return None
    return next(
        (
            item
            for item in EMPLOYEE_TEMPLATES
            if item.code == code
        ),
        None,
    )

from __future__ import annotations

import builtins
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ticket_agent.agent_skills.models import (
    AgentSkill,
    DigitalEmployeeSkillBinding,
)
from ticket_agent.agent_skills.service import AgentSkillService
from ticket_agent.digital_employees.draft_schemas import (
    DigitalEmployeeDraftCreate,
    DigitalEmployeeDraftList,
    DigitalEmployeeDraftReview,
    DigitalEmployeeDraftRevisionView,
    DigitalEmployeeDraftUpdate,
    DigitalEmployeeDraftView,
)
from ticket_agent.digital_employees.models import (
    DigitalEmployee,
    DigitalEmployeeDraft,
    DigitalEmployeeDraftRevision,
    DigitalEmployeeRevision,
    DigitalEmployeeRouteRule,
)
from ticket_agent.digital_employees.schemas import (
    DigitalEmployeeFromTemplateCreate,
)
from ticket_agent.digital_employees.service import (
    SUPPORTED_WORKFLOW_KEYS,
    DigitalEmployeeService,
)
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import get_settings
from ticket_agent.workforce.service import WorkforceTaskService


class DigitalEmployeeDraftService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_from_task(
        self,
        task_id: UUID,
        payload: DigitalEmployeeDraftCreate,
        *,
        actor_id: str,
    ) -> DigitalEmployeeDraft:
        task_service = WorkforceTaskService(self.session)
        task = task_service.get(task_id)
        task_view = task_service.view(task)
        gap = next(
            (
                item
                for item in task_view.capability_gaps
                if item.required_capability
                == payload.required_capability
            ),
            None,
        )
        if gap is None:
            raise ApiProblem(
                status_code=404,
                code="CAPABILITY_GAP_NOT_FOUND",
                title="Capability gap not found",
                detail=(
                    "The task does not contain the requested capability gap."
                ),
            )
        existing = self.session.scalar(
            select(DigitalEmployeeDraft).where(
                DigitalEmployeeDraft.source_task_id == task.id,
                DigitalEmployeeDraft.required_capability
                == payload.required_capability,
            )
        )
        if existing is not None:
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_DRAFT_EXISTS",
                title="Employee draft already exists",
                detail="This capability already has an employee draft.",
            )
        draft = DigitalEmployeeDraft(
            business_unit_id=task.business_unit_id,
            source_task_id=task.id,
            source_step_id=gap.step_id,
            required_capability=gap.required_capability,
            name=payload.name or gap.recommended_template_name,
            template_code=gap.recommended_template_code,
            domain=gap.recommended_domain,
            workflow_key=gap.recommended_workflow_key,
            scenario_type=(
                "hr_onboarding"
                if gap.recommended_domain == "human_resources"
                else "customer_service_ticket"
            ),
            handoff_queue="MANUAL_TRIAGE",
            capabilities_json=gap.recommended_capabilities,
            intents_json=gap.recommended_intents,
            skill_codes_json=gap.recommended_skills,
            tool_allowlist_json=gap.recommended_tools,
            status="DRAFT",
            created_by=actor_id,
        )
        self.session.add(draft)
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_DRAFT_EXISTS",
                title="Employee draft already exists",
                detail=(
                    "This capability already has an employee draft."
                ),
            ) from exc
        self._record_revision(
            draft,
            actor_id=actor_id,
            note="Employee draft created",
        )
        self.session.commit()
        self.session.refresh(draft)
        return draft

    def list(
        self,
        business_unit_id: str,
    ) -> DigitalEmployeeDraftList:
        rows = list(
            self.session.scalars(
                select(DigitalEmployeeDraft)
                .where(
                    DigitalEmployeeDraft.business_unit_id
                    == business_unit_id
                )
                .order_by(DigitalEmployeeDraft.created_at.desc())
                .limit(200)
            ).all()
        )
        total = self.session.scalar(
            select(func.count())
            .select_from(DigitalEmployeeDraft)
            .where(
                DigitalEmployeeDraft.business_unit_id
                == business_unit_id
            )
        ) or 0
        return DigitalEmployeeDraftList(
            items=[self.view(row) for row in rows],
            total=int(total),
        )

    def get(self, draft_id: UUID) -> DigitalEmployeeDraft:
        draft = self.session.get(DigitalEmployeeDraft, draft_id)
        if draft is None:
            raise ApiProblem(
                status_code=404,
                code="EMPLOYEE_DRAFT_NOT_FOUND",
                title="Employee draft not found",
                detail=f"Employee draft {draft_id} does not exist.",
            )
        return draft

    def get_for_update(self, draft_id: UUID) -> DigitalEmployeeDraft:
        draft = self.session.scalar(
            select(DigitalEmployeeDraft)
            .where(DigitalEmployeeDraft.id == draft_id)
            .with_for_update()
        )
        if draft is None:
            raise ApiProblem(
                status_code=404,
                code="EMPLOYEE_DRAFT_NOT_FOUND",
                title="Employee draft not found",
                detail=f"Employee draft {draft_id} does not exist.",
            )
        return draft

    def review(
        self,
        draft_id: UUID,
        payload: DigitalEmployeeDraftReview,
        *,
        actor_id: str,
    ) -> DigitalEmployeeDraft:
        draft = self.get_for_update(draft_id)
        if draft.status not in {"DRAFT", "IN_REVIEW"}:
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_DRAFT_STATE_CONFLICT",
                title="Employee draft cannot be reviewed",
                detail=f"Draft status is {draft.status}.",
            )
        if payload.decision == "REJECT" and not payload.note.strip():
            raise ApiProblem(
                status_code=422,
                code="EMPLOYEE_DRAFT_REJECTION_REASON_REQUIRED",
                title="Rejection reason is required",
                detail="Provide a reason when rejecting an employee draft.",
            )
        if (
            not get_settings().is_development
            and draft.created_by == actor_id
        ):
            raise ApiProblem(
                status_code=409,
                code="SEPARATION_OF_DUTIES_REQUIRED",
                title="Independent reviewer required",
                detail="The draft creator cannot approve or reject it.",
            )
        draft.status = (
            "APPROVED" if payload.decision == "APPROVE" else "REJECTED"
        )
        draft.review_note = payload.note
        draft.reviewed_by = actor_id
        draft.reviewed_at = datetime.now(UTC)
        draft.revision += 1
        self.session.flush()
        self._record_revision(
            draft,
            actor_id=actor_id,
            note=(
                f"Draft {payload.decision.lower()}d"
                + (
                    f": {payload.note.strip()}"
                    if payload.note.strip()
                    else ""
                )
            ),
        )
        self.session.commit()
        self.session.refresh(draft)
        return draft

    def update_draft(
        self,
        draft_id: UUID,
        payload: DigitalEmployeeDraftUpdate,
        *,
        actor_id: str,
    ) -> DigitalEmployeeDraft:
        draft = self.get_for_update(draft_id)
        if draft.status != "DRAFT":
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_DRAFT_NOT_EDITABLE",
                title="Employee draft is not editable",
                detail="Only a DRAFT can be edited. Reopen rejected drafts first.",
            )
        if payload.name is not None:
            draft.name = payload.name
        if payload.capabilities is not None:
            draft.capabilities_json = payload.capabilities
        if payload.intents is not None:
            draft.intents_json = payload.intents
        if payload.skill_codes is not None:
            draft.skill_codes_json = payload.skill_codes
        if payload.tool_allowlist is not None:
            draft.tool_allowlist_json = payload.tool_allowlist
        draft.revision += 1
        self.session.flush()
        self._record_revision(
            draft,
            actor_id=actor_id,
            note="Employee draft content updated",
        )
        self.session.commit()
        self.session.refresh(draft)
        return draft

    def reopen(
        self,
        draft_id: UUID,
        *,
        actor_id: str,
    ) -> DigitalEmployeeDraft:
        draft = self.get_for_update(draft_id)
        if draft.status != "REJECTED":
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_DRAFT_NOT_REJECTED",
                title="Only a rejected draft can be reopened",
                detail=f"Draft status is {draft.status}.",
            )
        previous_note = draft.review_note or ""
        draft.review_note = (
            f"{previous_note}\nReopened by {actor_id}".strip()
        )[:2000]
        draft.status = "DRAFT"
        draft.reviewed_by = None
        draft.reviewed_at = None
        draft.revision += 1
        self.session.flush()
        self._record_revision(
            draft,
            actor_id=actor_id,
            note="Rejected draft reopened for revision",
        )
        self.session.commit()
        self.session.refresh(draft)
        return draft

    def create_trial(
        self,
        draft_id: UUID,
        *,
        actor_id: str,
    ) -> DigitalEmployeeDraft:
        draft = self.get_for_update(draft_id)
        if draft.status != "APPROVED":
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_DRAFT_NOT_APPROVED",
                title="Employee draft not approved",
                detail="The draft must be approved before creating a trial.",
            )
        if draft.employee_id is not None:
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_DRAFT_TRIAL_EXISTS",
                title="Trial employee already exists",
                detail="This draft already has a trial employee.",
            )
        employee = (
            self._create_template_trial(draft, actor_id=actor_id)
            if draft.template_code
            else self._create_custom_trial(draft, actor_id=actor_id)
        )
        draft.employee_id = employee.id
        draft.status = "TRIAL"
        draft.evaluation_json = {}
        draft.evaluated_at = None
        draft.revision += 1
        self.session.flush()
        self._record_revision(
            draft,
            actor_id=actor_id,
            note=f"Trial employee {employee.id} created",
        )
        self.session.commit()
        self.session.refresh(draft)
        return draft

    def evaluate(
        self,
        draft_id: UUID,
        *,
        actor_id: str,
    ) -> DigitalEmployeeDraft:
        draft = self.get_for_update(draft_id)
        if draft.status not in {"TRIAL", "EVALUATION_FAILED"}:
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_DRAFT_NOT_IN_TRIAL",
                title="Employee draft is not in trial",
                detail="Evaluation requires a trial employee.",
            )
        employee = (
            self.session.get(DigitalEmployee, draft.employee_id)
            if draft.employee_id
            else None
        )
        if employee is None:
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_DRAFT_TRIAL_MISSING",
                title="Trial employee is missing",
                detail="The draft does not reference an existing employee.",
            )
        evaluation = self._evaluate_employee(employee)
        passed = bool(evaluation["passed"])
        draft.status = (
            "EVALUATION_PASSED" if passed else "EVALUATION_FAILED"
        )
        draft.evaluation_json = evaluation
        draft.evaluated_at = datetime.now(UTC)
        draft.revision += 1
        self.session.flush()
        self._record_revision(
            draft,
            actor_id=actor_id,
            note=(
                "Trial evaluation passed"
                if passed
                else "Trial evaluation failed"
            ),
        )
        self.session.commit()
        self.session.refresh(draft)
        return draft

    def publish(
        self,
        draft_id: UUID,
        *,
        actor_id: str,
    ) -> DigitalEmployeeDraft:
        draft = self.get_for_update(draft_id)
        if draft.status == "PUBLISHED":
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_DRAFT_ALREADY_PUBLISHED",
                title="Employee draft already published",
                detail="The draft has already been published.",
            )
        if draft.status != "EVALUATION_PASSED":
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_DRAFT_EVALUATION_REQUIRED",
                title="Evaluation required before publish",
                detail="The trial employee must pass evaluation first.",
            )
        employee = self._trial_employee(draft)
        current_evaluation = DigitalEmployeeService(
            self.session
        ).evaluate_resources(employee)
        evaluated_hash = draft.evaluation_json.get("resource_hash")
        if (
            not isinstance(evaluated_hash, str)
            or evaluated_hash != current_evaluation["resource_hash"]
            or current_evaluation["passed"] is not True
        ):
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_DRAFT_RESOURCES_CHANGED",
                title="Trial resources changed after evaluation",
                detail=(
                    "The employee resources changed after evaluation. "
                    "Run evaluation again before publishing."
                ),
            )
        employee.status = "ACTIVE"
        employee.config_revision += 1
        self._add_revision(
            employee,
            actor_id=actor_id,
            status="PUBLISHED",
            note="Published from employee draft",
        )
        draft.status = "PUBLISHED"
        draft.published_at = datetime.now(UTC)
        draft.revision += 1
        self.session.flush()
        self._record_revision(
            draft,
            actor_id=actor_id,
            note="Employee draft published",
        )
        self.session.commit()
        self.session.refresh(draft)
        return draft

    def rollback(
        self,
        draft_id: UUID,
        *,
        actor_id: str,
    ) -> DigitalEmployeeDraft:
        draft = self.get_for_update(draft_id)
        if draft.status != "PUBLISHED":
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_DRAFT_NOT_PUBLISHED",
                title="Only a published draft can be rolled back",
                detail="The draft is not in PUBLISHED status.",
            )
        employee = self._trial_employee(draft)
        employee.status = "DISABLED"
        employee.config_revision += 1
        self._add_revision(
            employee,
            actor_id=actor_id,
            status="ROLLED_BACK",
            note="Rolled back from employee draft",
        )
        draft.status = "ROLLED_BACK"
        draft.rolled_back_at = datetime.now(UTC)
        draft.revision += 1
        self.session.flush()
        self._record_revision(
            draft,
            actor_id=actor_id,
            note="Published employee rolled back",
        )
        self.session.commit()
        self.session.refresh(draft)
        return draft

    def _create_template_trial(
        self,
        draft: DigitalEmployeeDraft,
        *,
        actor_id: str,
    ) -> DigitalEmployee:
        if draft.template_code is None:
            raise AssertionError("template_code is required")
        return DigitalEmployeeService(self.session).create_from_template(
            DigitalEmployeeFromTemplateCreate(
                name=draft.name,
                template_code=draft.template_code,
                business_unit_id=draft.business_unit_id,
                change_note=(
                    f"Trial employee from draft {draft.id}"
                ),
            ),
            actor_id=actor_id,
            initial_status="TRIAL",
            template_overrides={
                "capabilities": list(draft.capabilities_json),
                "intents": list(draft.intents_json),
                "skill_codes": list(draft.skill_codes_json),
                "tool_allowlist": list(draft.tool_allowlist_json),
            },
            commit=False,
            validate_resources=False,
        )

    def _create_custom_trial(
        self,
        draft: DigitalEmployeeDraft,
        *,
        actor_id: str,
    ) -> DigitalEmployee:
        if draft.workflow_key not in SUPPORTED_WORKFLOW_KEYS:
            raise ApiProblem(
                status_code=422,
                code="UNSUPPORTED_WORKFLOW",
                title="Unsupported workflow",
                detail=(
                    f"Workflow '{draft.workflow_key}' is not registered."
                ),
            )
        suffix = uuid4().hex[:6]
        employee_key = f"trial_{draft.domain}_{suffix}"
        AgentSkillService(self.session).ensure_defaults(
            draft.business_unit_id,
            commit=False,
        )
        employee = DigitalEmployee(
            employee_key=employee_key,
            name=draft.name,
            version="0.1.0-trial",
            scenario_type=draft.scenario_type,
            domain=draft.domain,
            template_code=None,
            workflow_key=draft.workflow_key,
            business_unit_id=draft.business_unit_id,
            service_identity=f"digital_employee.{employee_key}",
            status="TRIAL",
            handoff_queue=draft.handoff_queue,
            knowledge_policy_json={
                "default_scope": {"audience": "support_agent"},
            },
            model_profile_json={},
            tool_allowlist_json=draft.tool_allowlist_json,
            manifest_json={
                "schema_version": 1,
                "domain": draft.domain,
                "template_code": None,
                "source_draft_id": str(draft.id),
                "capabilities": draft.capabilities_json,
                "intents": draft.intents_json,
                "required_resources": {
                    "knowledge_space_ids": [],
                    "skill_codes": sorted(set(draft.skill_codes_json)),
                    "mcp_tools": [],
                },
                "routing": {
                    "deterministic_first": True,
                    "llm_fallback_only": True,
                },
            },
            created_by=actor_id,
        )
        self.session.add(employee)
        self.session.flush()
        if draft.skill_codes_json:
            skills = list(
                self.session.scalars(
                    select(AgentSkill).where(
                        AgentSkill.business_unit_id
                        == draft.business_unit_id,
                        AgentSkill.code.in_(draft.skill_codes_json),
                        AgentSkill.status == "ACTIVE",
                    )
                ).all()
            )
            for skill in skills:
                self.session.add(
                    DigitalEmployeeSkillBinding(
                        employee_id=employee.id,
                        skill_id=skill.id,
                        enabled=True,
                        priority=100,
                    )
                )
        self.session.add(
            DigitalEmployeeRouteRule(
                business_unit_id=draft.business_unit_id,
                employee_id=employee.id,
                intents_json=draft.intents_json,
                categories_json=[],
                channels_json=[],
                priority=100,
                fallback=False,
                enabled=True,
            )
        )
        self._add_revision(
            employee,
            actor_id=actor_id,
            status="TRIAL",
            note=f"Trial employee from draft {draft.id}",
        )
        self.session.flush()
        return employee

    def _evaluate_employee(
        self,
        employee: DigitalEmployee,
    ) -> dict[str, object]:
        return DigitalEmployeeService(
            self.session
        ).evaluate_resources(employee)

    def _trial_employee(
        self,
        draft: DigitalEmployeeDraft,
    ) -> DigitalEmployee:
        employee = (
            self.session.get(DigitalEmployee, draft.employee_id)
            if draft.employee_id
            else None
        )
        if employee is None:
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_DRAFT_TRIAL_MISSING",
                title="Trial employee is missing",
                detail="The draft does not reference an existing employee.",
            )
        return employee

    def _add_revision(
        self,
        employee: DigitalEmployee,
        *,
        actor_id: str,
        status: str,
        note: str,
    ) -> None:
        self.session.add(
            DigitalEmployeeRevision(
                employee_id=employee.id,
                revision=employee.config_revision,
                status=status,
                manifest_json=employee.manifest_json,
                instruction_text=employee.instruction_text,
                change_note=note[:500],
                created_by=actor_id,
                published_at=(
                    datetime.now(UTC)
                    if status == "PUBLISHED"
                    else None
                ),
            )
        )

    def _record_revision(
        self,
        draft: DigitalEmployeeDraft,
        *,
        actor_id: str,
        note: str,
    ) -> None:
        self.session.add(
            DigitalEmployeeDraftRevision(
                draft_id=draft.id,
                revision=draft.revision,
                status=draft.status,
                snapshot_json=self.view(draft).model_dump(mode="json"),
                change_note=note[:500],
                created_by=actor_id,
            )
        )

    def record_external_change(
        self,
        draft: DigitalEmployeeDraft,
        *,
        actor_id: str,
        note: str,
    ) -> None:
        draft.revision += 1
        self.session.flush()
        self._record_revision(
            draft,
            actor_id=actor_id,
            note=note,
        )

    def list_revisions(
        self,
        draft_id: UUID,
    ) -> builtins.list[DigitalEmployeeDraftRevisionView]:
        self.get(draft_id)
        rows = self.session.scalars(
            select(DigitalEmployeeDraftRevision)
            .where(DigitalEmployeeDraftRevision.draft_id == draft_id)
            .order_by(DigitalEmployeeDraftRevision.revision.desc())
        ).all()
        return [
            DigitalEmployeeDraftRevisionView(
                id=row.id,
                draft_id=row.draft_id,
                revision=row.revision,
                status=row.status,
                snapshot=row.snapshot_json,
                change_note=row.change_note,
                created_by=row.created_by,
                created_at=row.created_at,
            )
            for row in rows
        ]

    @staticmethod
    def view(draft: DigitalEmployeeDraft) -> DigitalEmployeeDraftView:
        return DigitalEmployeeDraftView(
            id=draft.id,
            business_unit_id=draft.business_unit_id,
            source_task_id=draft.source_task_id,
            source_step_id=draft.source_step_id,
            required_capability=draft.required_capability,
            name=draft.name,
            template_code=draft.template_code,
            domain=draft.domain,
            workflow_key=draft.workflow_key,
            scenario_type=draft.scenario_type,
            handoff_queue=draft.handoff_queue,
            capabilities=draft.capabilities_json,
            intents=draft.intents_json,
            skill_codes=draft.skill_codes_json,
            tool_allowlist=draft.tool_allowlist_json,
            status=draft.status,
            revision=draft.revision,
            review_note=draft.review_note,
            created_by=draft.created_by,
            reviewed_by=draft.reviewed_by,
            reviewed_at=draft.reviewed_at,
            employee_id=draft.employee_id,
            evaluation=draft.evaluation_json,
            evaluated_at=draft.evaluated_at,
            published_at=draft.published_at,
            rolled_back_at=draft.rolled_back_at,
            promoted_template_id=draft.promoted_template_id,
            created_at=draft.created_at,
            updated_at=draft.updated_at,
        )

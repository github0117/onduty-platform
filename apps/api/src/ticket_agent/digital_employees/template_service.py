from __future__ import annotations

import builtins
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ticket_agent.agent_skills.models import (
    AgentSkill,
    DigitalEmployeeSkillBinding,
)
from ticket_agent.digital_employees.models import (
    DigitalEmployee,
    DigitalEmployeeDraft,
    DigitalEmployeeManagedTemplate,
    DigitalEmployeeTemplateRevision,
)
from ticket_agent.digital_employees.schemas import (
    DigitalEmployeeTemplateView,
    ManagedEmployeeTemplateReview,
    ManagedEmployeeTemplateRevisionView,
    ManagedEmployeeTemplateUpdate,
)
from ticket_agent.digital_employees.service import EmployeeTemplate
from ticket_agent.knowledge.models import (
    DigitalEmployeeKnowledgeBinding,
    KnowledgeSpace,
)
from ticket_agent.mcp_connectors.models import (
    DigitalEmployeeMcpBinding,
    McpConnector,
)
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import get_settings


class ManagedEmployeeTemplateService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def promote_from_draft(
        self,
        draft_id: UUID,
        *,
        actor_id: str,
    ) -> DigitalEmployeeManagedTemplate:
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
        if draft.status not in {"PUBLISHED", "ROLLED_BACK"}:
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_DRAFT_NOT_VALIDATED",
                title="Draft has not completed validation",
                detail=(
                    "Only a published or rolled-back validated draft can "
                    "be promoted to a template."
                ),
            )
        if draft.promoted_template_id is not None:
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_DRAFT_TEMPLATE_EXISTS",
                title="Draft already has a template",
                detail="This draft has already been promoted to a template.",
            )
        employee = (
            self.session.get(DigitalEmployee, draft.employee_id)
            if draft.employee_id
            else None
        )
        if employee is None:
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_DRAFT_EMPLOYEE_MISSING",
                title="Validated employee is missing",
                detail="The draft must reference a validated employee.",
            )
        skill_rows = self.session.execute(
            select(AgentSkill.code, AgentSkill.id)
            .join(
                DigitalEmployeeSkillBinding,
                DigitalEmployeeSkillBinding.skill_id == AgentSkill.id,
            )
            .where(
                DigitalEmployeeSkillBinding.employee_id == employee.id,
                DigitalEmployeeSkillBinding.enabled.is_(True),
            )
        ).all()
        knowledge_rows = list(
            self.session.scalars(
                select(DigitalEmployeeKnowledgeBinding).where(
                    DigitalEmployeeKnowledgeBinding.employee_id
                    == employee.id,
                    DigitalEmployeeKnowledgeBinding.enabled.is_(True),
                )
            ).all()
        )
        mcp_rows = list(
            self.session.scalars(
                select(DigitalEmployeeMcpBinding).where(
                    DigitalEmployeeMcpBinding.employee_id == employee.id,
                    DigitalEmployeeMcpBinding.enabled.is_(True),
                )
            ).all()
        )
        code = f"custom_{draft.domain}_{uuid4().hex[:6]}"
        template = DigitalEmployeeManagedTemplate(
            business_unit_id=draft.business_unit_id,
            code=code,
            name=draft.name,
            description=f"从员工草案 {draft.id} 沉淀的岗位模板。",
            domain=draft.domain,
            workflow_key=draft.workflow_key,
            scenario_type=draft.scenario_type,
            handoff_queue=draft.handoff_queue,
            capabilities_json=draft.capabilities_json,
            intents_json=draft.intents_json,
            skill_codes_json=[str(code) for code, _skill_id in skill_rows],
            tool_allowlist_json=list(employee.tool_allowlist_json),
            knowledge_bindings_json=[
                {
                    "knowledge_space_id": str(row.knowledge_space_id),
                    "workflow_key": row.workflow_key,
                    "scope": row.scope_json,
                    "enabled": True,
                }
                for row in knowledge_rows
            ],
            mcp_bindings_json=[
                {
                    "connector_id": str(row.connector_id),
                    "allowed_tools": list(row.allowed_tools_json),
                    "write_approved": row.write_approved,
                    "enabled": True,
                }
                for row in mcp_rows
            ],
            model_profile_json=employee.model_profile_json,
            knowledge_policy_json=employee.knowledge_policy_json,
            readiness_snapshot_json={
                "employee_evaluation": employee.activation_evaluation_json,
                "employee_activation_evaluated_at": (
                    employee.activation_evaluated_at.isoformat()
                    if employee.activation_evaluated_at
                    else None
                ),
            },
            version=1,
            status="DRAFT",
            source_draft_id=draft.id,
            created_by=actor_id,
        )
        self.session.add(template)
        self.session.flush()
        draft.promoted_template_id = template.id
        self._add_revision(
            template,
            actor_id=actor_id,
            note="Template draft promoted from employee draft",
        )
        from ticket_agent.digital_employees.draft_service import (
            DigitalEmployeeDraftService,
        )

        DigitalEmployeeDraftService(
            self.session
        ).record_external_change(
            draft,
            actor_id=actor_id,
            note=f"Promoted to template {template.code}",
        )
        self.session.commit()
        self.session.refresh(template)
        return template

    def list(
        self,
        business_unit_id: str,
        *,
        include_unpublished: bool = True,
    ) -> list[DigitalEmployeeManagedTemplate]:
        statement = select(DigitalEmployeeManagedTemplate).where(
            DigitalEmployeeManagedTemplate.business_unit_id
            == business_unit_id
        )
        if not include_unpublished:
            statement = statement.where(
                DigitalEmployeeManagedTemplate.status == "PUBLISHED"
            )
        return list(
            self.session.scalars(
                statement.order_by(
                    DigitalEmployeeManagedTemplate.created_at.desc()
                )
            ).all()
        )

    def get(
        self,
        template_id: UUID,
    ) -> DigitalEmployeeManagedTemplate:
        template = self.session.get(
            DigitalEmployeeManagedTemplate,
            template_id,
        )
        if template is None:
            raise ApiProblem(
                status_code=404,
                code="EMPLOYEE_TEMPLATE_NOT_FOUND",
                title="Employee template not found",
                detail=f"Employee template {template_id} does not exist.",
            )
        return template

    def get_for_update(
        self,
        template_id: UUID,
    ) -> DigitalEmployeeManagedTemplate:
        template = self.session.scalar(
            select(DigitalEmployeeManagedTemplate)
            .where(DigitalEmployeeManagedTemplate.id == template_id)
            .with_for_update()
        )
        if template is None:
            raise ApiProblem(
                status_code=404,
                code="EMPLOYEE_TEMPLATE_NOT_FOUND",
                title="Employee template not found",
                detail=f"Employee template {template_id} does not exist.",
            )
        return template

    def review(
        self,
        template_id: UUID,
        payload: ManagedEmployeeTemplateReview,
        *,
        actor_id: str,
    ) -> DigitalEmployeeManagedTemplate:
        template = self.get_for_update(template_id)
        if template.status not in {"DRAFT", "IN_REVIEW"}:
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_TEMPLATE_STATE_CONFLICT",
                title="Employee template cannot be reviewed",
                detail=f"Template status is {template.status}.",
            )
        if payload.decision == "REJECT" and not payload.note.strip():
            raise ApiProblem(
                status_code=422,
                code="EMPLOYEE_TEMPLATE_REJECTION_REASON_REQUIRED",
                title="Rejection reason is required",
                detail="Provide a reason when rejecting an employee template.",
            )
        if (
            not get_settings().is_development
            and template.created_by == actor_id
        ):
            raise ApiProblem(
                status_code=409,
                code="SEPARATION_OF_DUTIES_REQUIRED",
                title="Independent template reviewer required",
                detail="The template creator cannot approve or reject it.",
            )
        template.status = (
            "APPROVED" if payload.decision == "APPROVE" else "REJECTED"
        )
        template.version += 1
        template.review_note = payload.note
        template.reviewed_by = actor_id
        template.reviewed_at = datetime.now(UTC)
        self._add_revision(
            template,
            actor_id=actor_id,
            note=payload.note or f"Template {template.status.lower()}",
        )
        self.session.commit()
        self.session.refresh(template)
        return template

    def update_draft(
        self,
        template_id: UUID,
        payload: ManagedEmployeeTemplateUpdate,
        *,
        actor_id: str,
    ) -> DigitalEmployeeManagedTemplate:
        template = self.get_for_update(template_id)
        if template.status != "DRAFT":
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_TEMPLATE_NOT_EDITABLE",
                title="Employee template is not editable",
                detail="Only a DRAFT template can be edited.",
            )
        if payload.name is not None:
            template.name = payload.name
        if payload.description is not None:
            template.description = payload.description
        if payload.capabilities is not None:
            template.capabilities_json = payload.capabilities
        if payload.intents is not None:
            template.intents_json = payload.intents
        if payload.skill_codes is not None:
            template.skill_codes_json = payload.skill_codes
        if payload.tool_allowlist is not None:
            template.tool_allowlist_json = payload.tool_allowlist
        if payload.knowledge_bindings is not None:
            template.knowledge_bindings_json = payload.knowledge_bindings
        if payload.mcp_bindings is not None:
            template.mcp_bindings_json = payload.mcp_bindings
        template.version += 1
        self._add_revision(
            template,
            actor_id=actor_id,
            note="Template draft updated",
        )
        self.session.commit()
        self.session.refresh(template)
        return template

    def publish(
        self,
        template_id: UUID,
        *,
        actor_id: str,
    ) -> DigitalEmployeeManagedTemplate:
        template = self.get_for_update(template_id)
        if template.status != "APPROVED":
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_TEMPLATE_NOT_APPROVED",
                title="Employee template not approved",
                detail="The template must be approved before publishing.",
            )
        readiness = self._publish_readiness(template)
        if not readiness["passed"]:
            issues = readiness.get("issues", [])
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_TEMPLATE_NOT_READY",
                title="Employee template is not ready",
                detail="；".join(
                    str(issue)
                    for issue in (
                        issues if isinstance(issues, list) else []
                    )
                ),
            )
        template.readiness_snapshot_json = readiness
        template.status = "PUBLISHED"
        template.version += 1
        template.published_at = datetime.now(UTC)
        self._add_revision(
            template,
            actor_id=actor_id,
            note="Template published",
        )
        self.session.commit()
        self.session.refresh(template)
        return template

    def _publish_readiness(
        self,
        template: DigitalEmployeeManagedTemplate,
    ) -> dict[str, object]:
        issues: list[str] = []
        if not template.tool_allowlist_json:
            issues.append("模板未配置工具白名单")
        skill_codes = {
            str(value)
            for value in template.skill_codes_json
            if isinstance(value, str)
        }
        active_skill_codes = {
            str(row)
            for row in self.session.scalars(
                select(AgentSkill.code).where(
                    AgentSkill.business_unit_id
                    == template.business_unit_id,
                    AgentSkill.code.in_(skill_codes),
                    AgentSkill.status == "ACTIVE",
                )
            ).all()
        }
        missing_skills = sorted(skill_codes - active_skill_codes)
        if missing_skills:
            issues.append(
                "缺少启用 Skill：" + "、".join(missing_skills)
            )

        knowledge_ids = _binding_ids(
            template.knowledge_bindings_json,
            "knowledge_space_id",
        )
        active_knowledge_ids = {
            str(value)
            for value in self.session.scalars(
                select(KnowledgeSpace.id).where(
                    KnowledgeSpace.id.in_(knowledge_ids),
                    KnowledgeSpace.business_unit_id
                    == template.business_unit_id,
                    KnowledgeSpace.status == "ACTIVE",
                )
            ).all()
        }
        missing_knowledge = sorted(
            str(value)
            for value in knowledge_ids
            if str(value) not in active_knowledge_ids
        )
        if missing_knowledge:
            issues.append(
                "缺少可用知识空间："
                + "、".join(missing_knowledge)
            )
        if not knowledge_ids:
            issues.append("模板至少需要绑定一个知识空间")

        mcp_ids = _binding_ids(
            template.mcp_bindings_json,
            "connector_id",
        )
        connectors = {
            connector.id: connector
            for connector in self.session.scalars(
                select(McpConnector).where(
                    McpConnector.id.in_(mcp_ids),
                    McpConnector.business_unit_id
                    == template.business_unit_id,
                    McpConnector.status == "ACTIVE",
                )
            ).all()
        }
        for binding in template.mcp_bindings_json:
            connector_id = _binding_id(
                binding,
                "connector_id",
            )
            if connector_id is None:
                issues.append("MCP 绑定缺少有效 connector_id")
                continue
            connector = connectors.get(connector_id)
            if connector is None:
                issues.append(f"MCP {connector_id} 不可用")
                continue
            allowed = {
                str(value)
                for value in binding.get("allowed_tools", [])
                if isinstance(value, str)
            }
            available = {
                str(tool.get("name"))
                for tool in connector.tools_json
                if isinstance(tool, dict)
                and isinstance(tool.get("name"), str)
            }
            missing_tools = sorted(allowed - available)
            if missing_tools:
                issues.append(
                    f"MCP {connector.code} 缺少工具："
                    + "、".join(missing_tools)
                )
        return {
            "passed": not issues,
            "issues": issues,
            "checked_at": datetime.now(UTC).isoformat(),
            "skill_codes": sorted(skill_codes),
            "knowledge_space_ids": sorted(
                str(value) for value in knowledge_ids
            ),
            "mcp_connector_ids": sorted(
                str(value) for value in mcp_ids
            ),
        }

    def rollback(
        self,
        template_id: UUID,
        *,
        actor_id: str,
    ) -> DigitalEmployeeManagedTemplate:
        template = self.get_for_update(template_id)
        if template.status != "PUBLISHED":
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_TEMPLATE_NOT_PUBLISHED",
                title="Only a published template can be disabled",
                detail="The template is not currently published.",
            )
        template.status = "DISABLED"
        template.version += 1
        template.disabled_at = datetime.now(UTC)
        self._add_revision(
            template,
            actor_id=actor_id,
            note="Template disabled",
        )
        self.session.commit()
        self.session.refresh(template)
        return template

    def reopen(
        self,
        template_id: UUID,
        *,
        actor_id: str,
    ) -> DigitalEmployeeManagedTemplate:
        template = self.get_for_update(template_id)
        if template.status not in {"REJECTED", "DISABLED"}:
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_TEMPLATE_NOT_REOPENABLE",
                title="Template cannot be reopened",
                detail="Only rejected or disabled templates can be reopened.",
            )
        template.status = "DRAFT"
        template.version += 1
        template.reviewed_by = None
        template.reviewed_at = None
        template.published_at = None
        template.disabled_at = None
        self._add_revision(
            template,
            actor_id=actor_id,
            note="Template reopened for revision",
        )
        self.session.commit()
        self.session.refresh(template)
        return template

    def list_revisions(
        self,
        template_id: UUID,
    ) -> builtins.list[ManagedEmployeeTemplateRevisionView]:
        self.get(template_id)
        rows = list(
            self.session.scalars(
                select(DigitalEmployeeTemplateRevision)
                .where(
                    DigitalEmployeeTemplateRevision.template_id
                    == template_id
                )
                .order_by(DigitalEmployeeTemplateRevision.revision.desc())
            ).all()
        )
        return [
            ManagedEmployeeTemplateRevisionView(
                id=row.id,
                template_id=row.template_id,
                revision=row.revision,
                status=row.status,
                snapshot=row.snapshot_json,
                change_note=row.change_note,
                created_by=row.created_by,
                published_at=row.published_at,
                created_at=row.created_at,
            )
            for row in rows
        ]

    @staticmethod
    def view(
        template: DigitalEmployeeManagedTemplate,
    ) -> DigitalEmployeeTemplateView:
        return DigitalEmployeeTemplateView(
            id=template.id,
            code=template.code,
            name=template.name,
            description=template.description,
            domain=template.domain,
            workflow_key=template.workflow_key,
            scenario_type=template.scenario_type,
            handoff_queue=template.handoff_queue,
            capabilities=template.capabilities_json,
            intents=template.intents_json,
            skill_codes=template.skill_codes_json,
            tool_allowlist=template.tool_allowlist_json,
            status=template.status,
            builtin=False,
            source_draft_id=template.source_draft_id,
            version=template.version,
            published_at=template.published_at,
            knowledge_bindings=template.knowledge_bindings_json,
            mcp_bindings=template.mcp_bindings_json,
            model_profile=template.model_profile_json,
            knowledge_policy=template.knowledge_policy_json,
            readiness_snapshot=template.readiness_snapshot_json,
        )

    @staticmethod
    def employee_template(
        template: DigitalEmployeeManagedTemplate,
    ) -> EmployeeTemplate:
        return EmployeeTemplate(
            code=template.code,
            name=template.name,
            description=template.description,
            domain=template.domain,
            workflow_key=template.workflow_key,
            scenario_type=template.scenario_type,
            handoff_queue=template.handoff_queue,
            capabilities=list(template.capabilities_json),
            intents=list(template.intents_json),
            skill_codes=list(template.skill_codes_json),
            tool_allowlist=list(template.tool_allowlist_json),
            knowledge_bindings=list(template.knowledge_bindings_json),
            mcp_bindings=list(template.mcp_bindings_json),
            knowledge_policy=dict(template.knowledge_policy_json),
            model_profile=dict(template.model_profile_json),
            readiness_snapshot=dict(template.readiness_snapshot_json),
            activation_required=True,
            template_id=template.id,
            template_version=template.version,
        )

    def _add_revision(
        self,
        template: DigitalEmployeeManagedTemplate,
        *,
        actor_id: str,
        note: str,
    ) -> None:
        self.session.add(
            DigitalEmployeeTemplateRevision(
                template_id=template.id,
                revision=template.version,
                status=template.status,
                snapshot_json=self._snapshot(template),
                change_note=note[:500],
                created_by=actor_id,
                published_at=(
                    datetime.now(UTC)
                    if template.status == "PUBLISHED"
                    else None
                ),
            )
        )

    @staticmethod
    def _snapshot(
        template: DigitalEmployeeManagedTemplate,
    ) -> dict[str, object]:
        return {
            "code": template.code,
            "name": template.name,
            "description": template.description,
            "domain": template.domain,
            "workflow_key": template.workflow_key,
            "scenario_type": template.scenario_type,
            "handoff_queue": template.handoff_queue,
            "capabilities": template.capabilities_json,
            "intents": template.intents_json,
            "skill_codes": template.skill_codes_json,
            "tool_allowlist": template.tool_allowlist_json,
            "knowledge_bindings": template.knowledge_bindings_json,
            "mcp_bindings": template.mcp_bindings_json,
            "model_profile": template.model_profile_json,
            "knowledge_policy": template.knowledge_policy_json,
            "readiness_snapshot": template.readiness_snapshot_json,
            "status": template.status,
            "version": template.version,
        }


def _binding_ids(
    bindings: list[dict[str, object]],
    key: str,
) -> list[UUID]:
    return [
        value
        for binding in bindings
        if (value := _binding_id(binding, key)) is not None
    ]


def _binding_id(
    binding: dict[str, object],
    key: str,
) -> UUID | None:
    raw = binding.get(key)
    if not isinstance(raw, str):
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None

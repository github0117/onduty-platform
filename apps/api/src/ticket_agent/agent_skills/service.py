from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ticket_agent.agent_skills.contract import DEFAULT_SKILL_DEFINITIONS
from ticket_agent.agent_skills.models import AgentSkill, DigitalEmployeeSkillBinding
from ticket_agent.agent_skills.schemas import (
    AgentSkillCreate,
    AgentSkillUpdate,
    AgentSkillView,
    EmployeeSkillBindingView,
)
from ticket_agent.digital_employees.service import DigitalEmployeeService
from ticket_agent.shared.errors import ApiProblem


@dataclass(frozen=True)
class DefaultSkill:
    code: str
    name: str
    description: str
    triggers: list[str]
    instructions: str
    tools: list[str]


DEFAULT_SKILLS = (
    DefaultSkill(
        code="ecommerce-presales",
        name="电商售前咨询",
        description="商品参数、材质、使用方式和购买咨询。",
        triggers=["材质", "容量", "保温", "尺码", "颜色", "怎么用", "多少钱"],
        tools=["knowledge.search"],
        instructions=(
            "先检索员工授权的商品知识，仅依据知识回答静态参数。"
            "价格、库存、活动、发货时效和订单状态必须实时查询。"
            "不得补充知识中没有的参数、认证、功效或承诺。"
        ),
    ),
    DefaultSkill(
        code="ecommerce-aftersales",
        name="电商售后服务",
        description="退货、退款、换货、漏水和商品损坏等售后问题。",
        triggers=["退款", "退货", "换货", "售后", "漏水", "损坏", "赔偿"],
        tools=["knowledge.search"],
        instructions=(
            "先检索售后知识并核实用户诉求。不得自行承诺退款资格、金额或时效。"
            "涉及资金、退货或补偿时给出清晰的人工处理步骤，并升级人工。"
        ),
    ),
    DefaultSkill(
        code="logistics-inquiry",
        name="物流查询",
        description="快件轨迹、派送、签收和物流异常查询。",
        triggers=["物流", "快递", "运单", "到哪", "签收", "派送", "发货"],
        tools=["knowledge.search", "logistics.query"],
        instructions=(
            "先确认订单号或运单号。物流轨迹必须来自真实物流接口，"
            "未配置接口或无法查询时明确说明，不得猜测。"
        ),
    ),
    DefaultSkill(
        code="hr-onboarding",
        name="HR 入职支持",
        description="解释入职材料要求并检查资料完整性。",
        triggers=["入职", "劳动合同", "身份证明", "资料", "人事"],
        tools=["knowledge.search"],
        instructions=(
            "仅依据企业入职制度和员工已授权知识回答。"
            "不得承诺录用结果、薪资、社保生效时间或劳动合同条款，"
            "涉及个人敏感资料时只收集必要字段并转 HR 人工确认。"
        ),
    ),
    DefaultSkill(
        code="customer-service-supervisor",
        name="客服主管协调",
        description="拆解复杂客户问题并协调售前、售后、物流和人工资源。",
        triggers=["复杂问题", "协同", "主管", "多部门", "汇总", "统一处理"],
        tools=["ticket.read", "knowledge.search", "draft.create"],
        instructions=(
            "先识别客户问题涉及的售前、售后、物流和风险环节，"
            "将目标拆成可独立执行的子任务并指定专业员工。"
            "不得代替专业员工执行退款、补偿等外部写操作。"
        ),
    ),
)


class AgentSkillService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def ensure_defaults(
        self,
        business_unit_id: str,
        *,
        commit: bool = True,
    ) -> list[AgentSkill]:
        if self.session.get_bind().dialect.name == "postgresql":
            self.session.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtext(:lock_key))"
                ),
                {"lock_key": f"agent-skill-defaults:{business_unit_id}"},
            )
        existing = list(
            self.session.scalars(
                select(AgentSkill).where(
                    AgentSkill.business_unit_id == business_unit_id
                )
            ).all()
        )
        by_code = {skill.code: skill for skill in existing}
        created = False
        for default in DEFAULT_SKILLS:
            if default.code in by_code:
                # Older installs created the default skills before structured
                # contracts existed. Fill the definition once, and never
                # overwrite a definition someone has since edited.
                existing_skill = by_code[default.code]
                definition = DEFAULT_SKILL_DEFINITIONS.get(default.code)
                if (
                    existing_skill.definition_json is None
                    and definition is not None
                ):
                    existing_skill.definition_json = definition
                    existing_skill.definition_version = max(
                        existing_skill.definition_version,
                        1,
                    )
                    created = True
                continue
            definition = DEFAULT_SKILL_DEFINITIONS.get(default.code)
            skill = AgentSkill(
                business_unit_id=business_unit_id,
                code=default.code,
                name=default.name,
                description=default.description,
                instructions=default.instructions,
                triggers_json=default.triggers,
                tools_json=default.tools,
                definition_json=definition,
                definition_version=1 if definition is not None else 0,
                status="ACTIVE",
                created_by="system",
            )
            self.session.add(skill)
            by_code[default.code] = skill
            created = True
        if created and commit:
            self.session.commit()
        elif created:
            self.session.flush()
        return [
            by_code[default.code]
            for default in DEFAULT_SKILLS
            if default.code in by_code
        ]

    def list_skills(
        self,
        business_unit_id: str,
        *,
        commit: bool = True,
    ) -> list[AgentSkill]:
        self.ensure_defaults(business_unit_id, commit=commit)
        return list(
            self.session.scalars(
                select(AgentSkill)
                .where(AgentSkill.business_unit_id == business_unit_id)
                .order_by(AgentSkill.name)
            ).all()
        )

    def get(self, skill_id: UUID) -> AgentSkill:
        skill = self.session.get(AgentSkill, skill_id)
        if skill is None:
            raise ApiProblem(
                status_code=404,
                code="SKILL_NOT_FOUND",
                title="Skill not found",
                detail=f"Skill {skill_id} does not exist.",
            )
        return skill

    def create(
        self,
        payload: AgentSkillCreate,
        *,
        actor_id: str,
    ) -> AgentSkill:
        existing = self.session.scalar(
            select(AgentSkill).where(
                AgentSkill.business_unit_id == payload.business_unit_id,
                AgentSkill.code == payload.code,
            )
        )
        if existing is not None:
            raise ApiProblem(
                status_code=409,
                code="SKILL_EXISTS",
                title="Skill already exists",
                detail="Skill code must be unique within the business unit.",
            )
        definition = (
            payload.definition.to_json()
            if payload.definition is not None
            else None
        )
        skill = AgentSkill(
            business_unit_id=payload.business_unit_id,
            code=payload.code,
            name=payload.name,
            description=payload.description,
            instructions=payload.instructions,
            triggers_json=payload.triggers,
            tools_json=payload.tools,
            definition_json=definition,
            definition_version=1 if definition is not None else 0,
            status=payload.status,
            created_by=actor_id,
        )
        self.session.add(skill)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ApiProblem(
                status_code=409,
                code="SKILL_EXISTS",
                title="Skill already exists",
                detail="Skill code must be unique within the business unit.",
            ) from exc
        self.session.refresh(skill)
        return skill

    def update(
        self,
        skill_id: UUID,
        payload: AgentSkillUpdate,
        *,
        actor_id: str,
    ) -> AgentSkill:
        skill = self.get(skill_id)
        if (
            payload.expected_version is not None
            and payload.expected_version != skill.version
        ):
            raise ApiProblem(
                status_code=409,
                code="SKILL_VERSION_CONFLICT",
                title="Skill was modified",
                detail=(
                    f"Expected version {payload.expected_version}, "
                    f"found {skill.version}. Reload and retry."
                ),
            )
        for field, column in (
            ("name", "name"),
            ("description", "description"),
            ("instructions", "instructions"),
            ("status", "status"),
        ):
            value = getattr(payload, field)
            if value is not None:
                setattr(skill, column, value)
        if payload.triggers is not None:
            skill.triggers_json = payload.triggers
        if payload.tools is not None:
            skill.tools_json = payload.tools
        if payload.definition is not None:
            skill.definition_json = payload.definition.to_json()
            skill.definition_version += 1
        skill.version += 1
        self.session.flush()
        employee_ids = set(
            self.session.scalars(
                select(DigitalEmployeeSkillBinding.employee_id).where(
                    DigitalEmployeeSkillBinding.skill_id == skill.id,
                    DigitalEmployeeSkillBinding.enabled.is_(True),
                )
            ).all()
        )
        employee_service = DigitalEmployeeService(self.session)
        for employee_id in employee_ids:
            employee_service.invalidate_activation_if_changed(
                employee_service.get_for_update(employee_id),
                actor_id=actor_id,
                note=(
                    f"Skill {skill.code} changed; "
                    "employee reactivation required"
                ),
                require_baseline=True,
            )
        self.session.commit()
        self.session.refresh(skill)
        return skill

    def list_employee_bindings(
        self,
        employee_id: UUID,
    ) -> list[EmployeeSkillBindingView]:
        employee = DigitalEmployeeService(self.session).get(employee_id)
        self.ensure_defaults(employee.business_unit_id)
        rows = self.session.execute(
            select(DigitalEmployeeSkillBinding, AgentSkill)
            .join(AgentSkill, AgentSkill.id == DigitalEmployeeSkillBinding.skill_id)
            .where(DigitalEmployeeSkillBinding.employee_id == employee_id)
            .order_by(
                DigitalEmployeeSkillBinding.priority,
                AgentSkill.name,
            )
        ).all()
        return [
            self.binding_view(binding, skill)
            for binding, skill in rows
        ]

    def replace_employee_bindings(
        self,
        employee_id: UUID,
        bindings: list[dict[str, object]],
        *,
        commit: bool = True,
        actor_id: str = "system.skill_binding",
    ) -> list[EmployeeSkillBindingView]:
        employee_service = DigitalEmployeeService(self.session)
        employee = employee_service.get_for_update(employee_id)
        skill_ids = [
            binding["skill_id"]
            for binding in bindings
            if isinstance(binding.get("skill_id"), UUID)
        ]
        if len(skill_ids) != len(bindings):
            raise ApiProblem(
                status_code=422,
                code="SKILL_BINDING_INVALID",
                title="Invalid skill binding",
                detail="Every binding must include a valid skill_id.",
            )
        if len(skill_ids) != len(set(skill_ids)):
            raise ApiProblem(
                status_code=422,
                code="SKILL_BINDING_DUPLICATED",
                title="Duplicate skill binding",
                detail="Each Skill can appear only once in employee bindings.",
            )
        skills = list(
            self.session.scalars(
                select(AgentSkill).where(AgentSkill.id.in_(skill_ids))
            ).all()
        )
        if len(skills) != len(set(skill_ids)):
            raise ApiProblem(
                status_code=422,
                code="SKILL_NOT_FOUND",
                title="Skill not found",
                detail="One or more skill IDs do not exist.",
            )
        if any(skill.business_unit_id != employee.business_unit_id for skill in skills):
            raise ApiProblem(
                status_code=422,
                code="SKILL_UNIT_MISMATCH",
                title="Skill belongs to another business unit",
                detail="Employee and skill must belong to the same business unit.",
            )
        self.session.execute(
            delete(DigitalEmployeeSkillBinding).where(
                DigitalEmployeeSkillBinding.employee_id == employee_id
            )
        )
        created: list[tuple[DigitalEmployeeSkillBinding, AgentSkill]] = []
        skill_by_id = {skill.id: skill for skill in skills}
        for raw in bindings:
            skill_id = raw["skill_id"]
            if not isinstance(skill_id, UUID):
                continue
            raw_priority = raw.get("priority", 100)
            binding = DigitalEmployeeSkillBinding(
                employee_id=employee_id,
                skill_id=skill_id,
                enabled=bool(raw.get("enabled", True)),
                priority=(
                    raw_priority
                    if isinstance(raw_priority, int)
                    else 100
                ),
            )
            self.session.add(binding)
            created.append((binding, skill_by_id[skill_id]))
        self.session.flush()
        if commit:
            employee_service.invalidate_activation_if_changed(
                employee,
                actor_id=actor_id,
                note="Employee Skill bindings changed; reactivation required",
            )
            self.session.commit()
        return [
            self.binding_view(binding, skill)
            for binding, skill in sorted(
                created,
                key=lambda item: (item[0].priority, item[1].name),
            )
        ]

    def resolve_employee_skills(
        self,
        employee_id: UUID,
        business_unit_id: str,
    ) -> list[AgentSkill]:
        defaults = self.ensure_defaults(business_unit_id)
        rows = list(
            self.session.scalars(
                select(AgentSkill)
                .join(
                    DigitalEmployeeSkillBinding,
                    DigitalEmployeeSkillBinding.skill_id == AgentSkill.id,
                )
                .where(
                    DigitalEmployeeSkillBinding.employee_id == employee_id,
                    DigitalEmployeeSkillBinding.enabled.is_(True),
                    AgentSkill.status == "ACTIVE",
                )
                .order_by(DigitalEmployeeSkillBinding.priority)
            ).all()
        )
        return rows or defaults

    @staticmethod
    def view(skill: AgentSkill) -> AgentSkillView:
        return AgentSkillView(
            id=skill.id,
            business_unit_id=skill.business_unit_id,
            code=skill.code,
            name=skill.name,
            description=skill.description,
            instructions=skill.instructions,
            triggers=skill.triggers,
            tools=skill.tools,
            definition=skill.definition_json,
            definition_version=skill.definition_version,
            status=skill.status,
            version=skill.version,
            created_by=skill.created_by,
            created_at=skill.created_at,
            updated_at=skill.updated_at,
        )

    @staticmethod
    def binding_view(
        binding: DigitalEmployeeSkillBinding,
        skill: AgentSkill,
    ) -> EmployeeSkillBindingView:
        return EmployeeSkillBindingView(
            id=binding.id,
            employee_id=binding.employee_id,
            skill_id=binding.skill_id,
            skill_code=skill.code,
            skill_name=skill.name,
            enabled=binding.enabled,
            priority=binding.priority,
        )

import hashlib
import json
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ticket_agent.digital_employees.models import (
    DigitalEmployee,
    DigitalEmployeeManagedTemplate,
    DigitalEmployeeRevision,
    DigitalEmployeeRouteDecision,
    DigitalEmployeeRouteRule,
)
from ticket_agent.digital_employees.schemas import (
    DigitalEmployeeConfigurationUpdate,
    DigitalEmployeeCreate,
    DigitalEmployeeFromTemplateCreate,
    DigitalEmployeeRevisionView,
    DigitalEmployeeRouteDecisionList,
    DigitalEmployeeRouteDecisionView,
    DigitalEmployeeRouteRuleUpdate,
    DigitalEmployeeRouteRuleView,
    DigitalEmployeeTemplateView,
    DigitalEmployeeUpdate,
    DigitalEmployeeView,
)
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

DEFAULT_EMPLOYEE_KEY = "customer_service_ticket_v1"
SUPPORTED_WORKFLOW_KEYS = {
    "customer_service_ticket_v1",
    "hr_onboarding_document_collection_v1",
}


@dataclass(frozen=True)
class EmployeeTemplate:
    code: str
    name: str
    description: str
    domain: str
    workflow_key: str
    scenario_type: str
    handoff_queue: str
    capabilities: list[str]
    intents: list[str]
    skill_codes: list[str]
    tool_allowlist: list[str]
    knowledge_bindings: list[dict[str, object]] = dataclass_field(
        default_factory=list
    )
    mcp_bindings: list[dict[str, object]] = dataclass_field(
        default_factory=list
    )
    knowledge_policy: dict[str, object] = dataclass_field(
        default_factory=dict
    )
    model_profile: dict[str, object] = dataclass_field(
        default_factory=dict
    )
    readiness_snapshot: dict[str, object] = dataclass_field(
        default_factory=dict
    )
    activation_required: bool = False
    template_id: UUID | None = None
    template_version: int = 1


EMPLOYEE_TEMPLATES = (
    EmployeeTemplate(
        code="enterprise_service_desk",
        name="企业服务台数字员工",
        description="处理制度咨询、IT 报障、账号权限和内部流程请求。",
        domain="customer_service",
        workflow_key="customer_service_ticket_v1",
        scenario_type="enterprise_service",
        handoff_queue="ENTERPRISE_SERVICE_DESK",
        capabilities=["企业制度回答", "内部流程说明", "IT 与账号支持", "人工交接"],
        intents=[
            "企业服务",
            "制度",
            "流程",
            "通知",
            "账号",
            "登录",
            "密码",
            "权限",
            "IT",
            "邮箱",
            "入职",
        ],
        skill_codes=[],
        tool_allowlist=[
            "ticket.read",
            "knowledge.search",
            "draft.create",
            "ticket.sync",
        ],
    ),
    EmployeeTemplate(
        code="ecommerce_presales",
        name="电商售前客服",
        description="回答商品参数、使用方法、库存和购买前咨询。",
        domain="customer_service",
        workflow_key="customer_service_ticket_v1",
        scenario_type="customer_service_ticket",
        handoff_queue="ECOMMERCE_PRESALES",
        capabilities=["商品知识回答", "购买咨询", "商品参数解释"],
        intents=[
            "商品参数",
            "容量",
            "颜色",
            "材质",
            "尺寸",
            "使用方法",
            "购买咨询",
        ],
        skill_codes=["ecommerce-presales"],
        tool_allowlist=["ticket.read", "knowledge.search", "draft.create"],
    ),
    EmployeeTemplate(
        code="ecommerce_aftersales",
        name="电商售后客服",
        description="处理退换货、损坏、退款说明和售后风险升级。",
        domain="customer_service",
        workflow_key="customer_service_ticket_v1",
        scenario_type="customer_service_ticket",
        handoff_queue="ECOMMERCE_AFTERSALES",
        capabilities=["售后知识回答", "退款说明", "高风险转人工"],
        intents=["退货", "退款", "换货", "商品损坏", "售后"],
        skill_codes=["ecommerce-aftersales"],
        tool_allowlist=[
            "ticket.read",
            "knowledge.search",
            "draft.create",
        ],
    ),
    EmployeeTemplate(
        code="ecommerce_logistics",
        name="物流查询客服",
        description="查询订单物流、派送、签收和物流异常。",
        domain="customer_service",
        workflow_key="customer_service_ticket_v1",
        scenario_type="customer_service_ticket",
        handoff_queue="ECOMMERCE_LOGISTICS",
        capabilities=["实时物流查询", "订单轨迹说明", "物流异常转人工"],
        intents=["物流", "快递", "运单", "派送", "签收"],
        skill_codes=["logistics-inquiry"],
        tool_allowlist=["ticket.read", "knowledge.search", "draft.create"],
    ),
    EmployeeTemplate(
        code="ecommerce_listing_operator",
        name="商品上架数字员工",
        description="校验商品资料和平台规则，生成上架内容并提交人工审核。",
        domain="ecommerce_operations",
        workflow_key="customer_service_ticket_v1",
        scenario_type="ecommerce_operations",
        handoff_queue="ECOMMERCE_LISTING_REVIEW",
        capabilities=["商品资料校验", "上架内容生成", "合规规则检查"],
        intents=["上架", "商品资料", "标题", "卖点", "详情"],
        skill_codes=["ecommerce-listing-operations"],
        tool_allowlist=["knowledge.search", "draft.create"],
    ),
    EmployeeTemplate(
        code="ecommerce_visual_creator",
        name="视觉内容数字员工",
        description="制作主图、分镜、视频和字幕，并检查素材质量。",
        domain="content_media",
        workflow_key="customer_service_ticket_v1",
        scenario_type="ecommerce_operations",
        handoff_queue="ECOMMERCE_VISUAL_REVIEW",
        capabilities=["主图生成", "分镜与视频制作", "素材质量检查"],
        intents=["主图", "图片", "分镜", "视频", "字幕", "素材"],
        skill_codes=["ecommerce-visual-operations"],
        tool_allowlist=["knowledge.search", "draft.create"],
    ),
    EmployeeTemplate(
        code="ecommerce_operations_supervisor",
        name="电商运营主管数字员工",
        description="汇总商品、素材和上架质量，识别返工与成本异常。",
        domain="ecommerce_operations",
        workflow_key="customer_service_ticket_v1",
        scenario_type="ecommerce_operations",
        handoff_queue="ECOMMERCE_OPERATIONS_REVIEW",
        capabilities=["运营质量汇总", "异常识别", "人工升级建议"],
        intents=["运营汇总", "成本", "返工", "异常", "质量"],
        skill_codes=["ecommerce-operations-supervision"],
        tool_allowlist=["knowledge.search", "draft.create"],
    ),
    EmployeeTemplate(
        code="hr_onboarding",
        name="HR 入职专员",
        description="收集新员工资料、解释入职材料要求并跟踪缺失项。",
        domain="human_resources",
        workflow_key="hr_onboarding_document_collection_v1",
        scenario_type="hr_onboarding",
        handoff_queue="HR_SERVICE_DESK",
        capabilities=["入职资料收集", "材料完整性检查", "HR 人工交接"],
        intents=["入职", "劳动合同", "身份证明", "入职材料", "资料"],
        skill_codes=["hr-onboarding"],
        tool_allowlist=["ticket.read", "knowledge.search", "draft.create"],
    ),
    EmployeeTemplate(
        code="customer_service_supervisor",
        name="客服主管数字员工",
        description="拆解复杂客户问题并协调多个专业数字员工。",
        domain="customer_service",
        workflow_key="customer_service_ticket_v1",
        scenario_type="customer_service_ticket",
        handoff_queue="MANUAL_TRIAGE",
        capabilities=["复杂任务拆解", "专业员工协调", "结果汇总"],
        intents=[
            "复杂问题",
            "协同处理",
            "多部门",
            "主管协调",
            "汇总",
            "统一处理",
        ],
        skill_codes=["customer-service-supervisor"],
        tool_allowlist=["ticket.read", "knowledge.search", "draft.create"],
    ),
)


class DigitalEmployeeService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def ensure_default(self, business_unit_id: str) -> DigitalEmployee:
        if self.session.get_bind().dialect.name == "postgresql":
            self.session.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtext(:lock_key))"
                ),
                {
                    "lock_key": (
                        f"digital-employee-default:{business_unit_id}"
                    )
                },
            )
        employee = self.session.scalar(
            select(DigitalEmployee).where(
                DigitalEmployee.business_unit_id == business_unit_id,
                DigitalEmployee.employee_key == DEFAULT_EMPLOYEE_KEY,
            )
        )
        if employee is not None:
            return employee
        employee = DigitalEmployee(
            employee_key=DEFAULT_EMPLOYEE_KEY,
            name="客服工单数字员工",
            version="1.0.0",
            scenario_type="customer_service_ticket",
            domain="customer_service",
            workflow_key="customer_service_ticket_v1",
            business_unit_id=business_unit_id,
            service_identity="digital_agent.ticket.v1",
            handoff_queue="MANUAL_TRIAGE",
            knowledge_policy_json={
                "default_scope": {"audience": "support_agent"},
            },
            model_profile_json={},
            tool_allowlist_json=[
                "ticket.read",
                "knowledge.search",
                "draft.create",
                "ticket.sync",
            ],
            manifest_json=_manifest(
                domain="customer_service",
                template_code="legacy_customer_service",
                capabilities=["客服工单处理"],
                intents=["通用客服"],
            ),
            created_by="system",
        )
        self.session.add(employee)
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            raise ApiProblem(
                status_code=409,
                code="DIGITAL_EMPLOYEE_EXISTS",
                title="Digital employee already exists",
                detail=(
                    "employee_key must be unique within the business unit."
                ),
            ) from exc
        self._add_route_rule(
            employee,
            intents=["通用客服"],
            fallback=True,
        )
        self._add_revision(
            employee,
            actor_id="system",
            change_note="System default employee",
        )
        return employee

    def list_employees(
        self,
        business_unit_id: str | None,
    ) -> list[DigitalEmployee]:
        statement = select(DigitalEmployee).order_by(
            DigitalEmployee.business_unit_id,
            DigitalEmployee.name,
        )
        if business_unit_id:
            statement = statement.where(
                DigitalEmployee.business_unit_id == business_unit_id
            )
        return list(self.session.scalars(statement).all())

    def get(self, employee_id: UUID) -> DigitalEmployee:
        employee = self.session.get(DigitalEmployee, employee_id)
        if employee is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Digital employee not found",
                detail=f"Digital employee {employee_id} does not exist.",
            )
        return employee

    def get_for_update(self, employee_id: UUID) -> DigitalEmployee:
        employee = self.session.scalar(
            select(DigitalEmployee)
            .where(DigitalEmployee.id == employee_id)
            .with_for_update()
        )
        if employee is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Digital employee not found",
                detail=f"Digital employee {employee_id} does not exist.",
            )
        return employee

    def create(
        self,
        payload: DigitalEmployeeCreate,
        *,
        actor_id: str,
    ) -> DigitalEmployee:
        self._validate_workflow(payload.workflow_key)
        initial_status = (
            "ACTIVE"
            if get_settings().is_development
            else "TRIAL"
        )
        existing = self.session.scalar(
            select(DigitalEmployee).where(
                DigitalEmployee.business_unit_id == payload.business_unit_id,
                DigitalEmployee.employee_key == payload.employee_key,
            )
        )
        if existing is not None:
            raise ApiProblem(
                status_code=409,
                code="DIGITAL_EMPLOYEE_EXISTS",
                title="Digital employee already exists",
                detail="employee_key must be unique within the business unit.",
            )
        employee = DigitalEmployee(
            employee_key=payload.employee_key,
            name=payload.name,
            version=payload.version,
            scenario_type=payload.scenario_type,
            domain=_domain_for_workflow(payload.workflow_key),
            template_code=None,
            workflow_key=payload.workflow_key,
            business_unit_id=payload.business_unit_id,
            service_identity=payload.service_identity,
            status=initial_status,
            handoff_queue=payload.handoff_queue,
            knowledge_policy_json=payload.knowledge_policy,
            model_profile_json=payload.model_profile,
            tool_allowlist_json=payload.tool_allowlist,
            instruction_text=payload.instruction,
            manifest_json=_manifest(
                domain=_domain_for_workflow(payload.workflow_key),
                template_code=None,
                capabilities=[],
                intents=[],
            )
            | {
                "activation_required": initial_status == "TRIAL",
                "template_id": None,
                "template_version": None,
                "required_resources": {
                    "knowledge_space_ids": [],
                    "skill_codes": [],
                    "mcp_tools": [],
                },
            },
            created_by=actor_id,
        )
        self.session.add(employee)
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            raise ApiProblem(
                status_code=409,
                code="DIGITAL_EMPLOYEE_EXISTS",
                title="Digital employee already exists",
                detail=(
                    "employee_key must be unique within the business unit."
                ),
            ) from exc
        self._add_route_rule(
            employee,
            intents=[],
            fallback=True,
        )
        self._add_revision(
            employee,
            actor_id=actor_id,
            change_note="Initial employee configuration",
        )
        self.session.commit()
        self.session.refresh(employee)
        return employee

    def update(
        self,
        employee_id: UUID,
        payload: DigitalEmployeeUpdate,
        *,
        actor_id: str = "system",
    ) -> DigitalEmployee:
        employee = self.get_for_update(employee_id)
        if payload.status == "ACTIVE" and employee.status != "ACTIVE":
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_ACTIVATION_REQUIRED",
                title="Employee activation evaluation required",
                detail=(
                    "A non-active employee must pass activation evaluation "
                    "through the activation endpoint."
                ),
            )
        if payload.workflow_key is not None:
            self._validate_workflow(payload.workflow_key)
            employee.workflow_key = payload.workflow_key
        for field, column in (
            ("name", "name"),
            ("version", "version"),
            ("scenario_type", "scenario_type"),
            ("service_identity", "service_identity"),
            ("status", "status"),
            ("handoff_queue", "handoff_queue"),
            ("instruction", "instruction_text"),
        ):
            value = getattr(payload, field)
            if value is not None:
                setattr(employee, column, value)
        if payload.knowledge_policy is not None:
            employee.knowledge_policy_json = payload.knowledge_policy
        if payload.model_profile is not None:
            employee.model_profile_json = payload.model_profile
        if payload.tool_allowlist is not None:
            employee.tool_allowlist_json = payload.tool_allowlist
        employee.manifest_json = {
            **employee.manifest_json,
            **_manifest(
                domain=employee.domain,
                template_code=employee.template_code,
                capabilities=[
                    str(item)
                    for item in employee.manifest_json.get("capabilities", [])
                    if isinstance(item, str)
                ],
                intents=[
                    str(item)
                    for item in employee.manifest_json.get("intents", [])
                    if isinstance(item, str)
                ],
            ),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        self.session.flush()
        invalidated = False
        if employee.status != "DISABLED":
            invalidated = self.invalidate_activation_if_changed(
                employee,
                actor_id=actor_id,
                note="Employee configuration changed; reactivation required",
                require_baseline=any(
                    value is not None
                    for value in (
                        payload.workflow_key,
                        payload.tool_allowlist,
                        payload.model_profile,
                        payload.knowledge_policy,
                    )
                ),
            )
        if not invalidated:
            employee.config_revision += 1
            self._add_revision(
                employee,
                actor_id=actor_id,
                change_note="Employee configuration updated",
                status=_revision_status(employee),
            )
        self.session.commit()
        self.session.refresh(employee)
        return employee

    def update_configuration(
        self,
        employee_id: UUID,
        payload: DigitalEmployeeConfigurationUpdate,
        *,
        actor_id: str,
    ) -> DigitalEmployee:
        employee = self.get_for_update(employee_id)
        if payload.status == "ACTIVE" and employee.status != "ACTIVE":
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_ACTIVATION_REQUIRED",
                title="Employee activation evaluation required",
                detail=(
                    "Use the activation endpoint to re-evaluate and enable "
                    "a non-active employee."
                ),
            )
        for field, column in (
            ("name", "name"),
            ("status", "status"),
            ("handoff_queue", "handoff_queue"),
            ("instruction", "instruction_text"),
        ):
            value = getattr(payload, field)
            if value is not None:
                setattr(employee, column, value)
        if payload.knowledge_policy is not None:
            employee.knowledge_policy_json = payload.knowledge_policy
        if payload.model_profile is not None:
            employee.model_profile_json = payload.model_profile
        if payload.tool_allowlist is not None:
            employee.tool_allowlist_json = payload.tool_allowlist
        self.session.flush()

        from ticket_agent.agent_skills.service import AgentSkillService
        from ticket_agent.knowledge.service import KnowledgeService
        from ticket_agent.mcp_connectors.service import McpConnectorService

        if payload.knowledge_bindings is not None:
            KnowledgeService(self.session).replace_employee_bindings(
                employee_id,
                bindings=[
                    {
                        "knowledge_space_id": binding.knowledge_space_id,
                        "workflow_key": binding.workflow_key,
                        "scope": binding.scope,
                        "enabled": binding.enabled,
                    }
                    for binding in payload.knowledge_bindings
                ],
                commit=False,
                actor_id=actor_id,
            )
        if payload.skill_bindings is not None:
            AgentSkillService(
                self.session
            ).replace_employee_bindings(
                employee_id,
                [
                    binding.model_dump()
                    for binding in payload.skill_bindings
                ],
                commit=False,
                actor_id=actor_id,
            )
        if payload.mcp_bindings is not None:
            McpConnectorService(
                self.session
            ).replace_employee_bindings(
                employee_id,
                [
                    binding.model_dump()
                    for binding in payload.mcp_bindings
                ],
                commit=False,
                actor_id=actor_id,
            )
        self.session.flush()
        employee.manifest_json = {
            **employee.manifest_json,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        invalidated = (
            employee.status != "DISABLED"
            and self.invalidate_activation_if_changed(
                employee,
                actor_id=actor_id,
                note=(
                    "Employee configuration or resources changed; "
                    "reactivation required"
                ),
                require_baseline=True,
            )
        )
        if not invalidated:
            employee.config_revision += 1
            self._add_revision(
                employee,
                actor_id=actor_id,
                change_note="Employee configuration updated atomically",
                status=_revision_status(employee),
            )
        self.session.commit()
        self.session.refresh(employee)
        return employee

    def list_templates(
        self,
        business_unit_id: str,
    ) -> list[DigitalEmployeeTemplateView]:
        managed = list(
            self.session.scalars(
                select(DigitalEmployeeManagedTemplate)
                .where(
                    DigitalEmployeeManagedTemplate.business_unit_id
                    == business_unit_id,
                    DigitalEmployeeManagedTemplate.status
                    == "PUBLISHED",
                )
                .order_by(DigitalEmployeeManagedTemplate.name)
            ).all()
        )
        return [
            DigitalEmployeeTemplateView(
                code=template.code,
                name=template.name,
                description=template.description,
                domain=template.domain,
                workflow_key=template.workflow_key,
                scenario_type=template.scenario_type,
                handoff_queue=template.handoff_queue,
                capabilities=template.capabilities,
                intents=template.intents,
                skill_codes=template.skill_codes,
                tool_allowlist=template.tool_allowlist,
                status="PUBLISHED",
                builtin=True,
            )
            for template in EMPLOYEE_TEMPLATES
        ] + [
            _managed_template_view(template)
            for template in managed
        ]

    def create_from_template(
        self,
        payload: DigitalEmployeeFromTemplateCreate,
        *,
        actor_id: str,
        initial_status: str = "ACTIVE",
        template_overrides: dict[str, object] | None = None,
        commit: bool = True,
        validate_resources: bool = True,
    ) -> DigitalEmployee:
        template = self._resolve_template(
            payload.template_code,
            payload.business_unit_id,
        )
        if template_overrides:
            template = replace(
                template,
                capabilities=_string_list_or(
                    template_overrides.get("capabilities"),
                    template.capabilities,
                ),
                intents=_string_list_or(
                    template_overrides.get("intents"),
                    template.intents,
                ),
                skill_codes=_string_list_or(
                    template_overrides.get("skill_codes"),
                    template.skill_codes,
                ),
                tool_allowlist=_string_list_or(
                    template_overrides.get("tool_allowlist"),
                    template.tool_allowlist,
                ),
            )
        self._validate_workflow(template.workflow_key)
        resolved_status = initial_status
        if (
            initial_status == "ACTIVE"
            and (
                template.activation_required
                or not get_settings().is_development
            )
        ):
            resolved_status = "TRIAL"
        from ticket_agent.agent_skills.service import AgentSkillService

        AgentSkillService(self.session).ensure_defaults(
            payload.business_unit_id,
            commit=commit,
        )
        if validate_resources:
            self._validate_template_resources(
                template,
                business_unit_id=payload.business_unit_id,
            )
        suffix = uuid4().hex[:6]
        employee_key = f"{template.code}_{suffix}"
        manifest = _manifest(
            domain=template.domain,
            template_code=template.code,
            capabilities=template.capabilities,
            intents=template.intents,
        )
        manifest["activation_required"] = (
            template.activation_required
            or resolved_status == "TRIAL"
        )
        manifest["template_id"] = (
            str(template.template_id)
            if template.template_id is not None
            else None
        )
        manifest["template_version"] = template.template_version
        manifest["required_resources"] = {
            "knowledge_space_ids": [
                str(value)
                for value in _binding_uuid_values(
                    template.knowledge_bindings,
                    "knowledge_space_id",
                )
            ],
            "skill_codes": list(template.skill_codes),
            "mcp_tools": [
                {
                    "connector_id": str(
                        binding.get("connector_id")
                    ),
                    "allowed_tools": _string_list(
                        binding.get("allowed_tools")
                    ),
                }
                for binding in template.mcp_bindings
            ],
        }
        employee = DigitalEmployee(
            employee_key=employee_key,
            name=payload.name,
            version="1.0.0",
            scenario_type=template.scenario_type,
            domain=template.domain,
            template_code=template.code,
            workflow_key=template.workflow_key,
            business_unit_id=payload.business_unit_id,
            service_identity=f"digital_employee.{employee_key}",
            status=resolved_status,
            handoff_queue=template.handoff_queue,
            knowledge_policy_json=(
                template.knowledge_policy
                or {"default_scope": {"audience": "support_agent"}}
            ),
            model_profile_json=(
                payload.model_profile or template.model_profile
            ),
            tool_allowlist_json=template.tool_allowlist,
            manifest_json=manifest,
            created_by=actor_id,
        )
        self.session.add(employee)
        self.session.flush()
        self._add_route_rule(
            employee,
            intents=template.intents,
            fallback=False,
        )
        required_knowledge_ids = _binding_uuid_values(
            template.knowledge_bindings,
            "knowledge_space_id",
        )
        required_mcp_ids = _binding_uuid_values(
            template.mcp_bindings,
            "connector_id",
        )
        self._bind_template_resources(
            employee,
            template,
            knowledge_space_ids=list(
                dict.fromkeys(
                    [
                        *payload.knowledge_space_ids,
                        *required_knowledge_ids,
                    ]
                )
            ),
            skill_ids=payload.skill_ids,
            mcp_connector_ids=list(
                dict.fromkeys(
                    [
                        *payload.mcp_connector_ids,
                        *required_mcp_ids,
                    ]
                )
            ),
            commit=commit,
        )
        self._add_revision(
            employee,
            actor_id=actor_id,
            change_note=payload.change_note or "Created from template",
            status=(
                "TRIAL"
                if resolved_status == "TRIAL"
                else "PUBLISHED"
            ),
        )
        if commit:
            self.session.commit()
            self.session.refresh(employee)
        else:
            self.session.flush()
        return employee

    def _resolve_template(
        self,
        code: str,
        business_unit_id: str,
    ) -> EmployeeTemplate:
        builtin = next(
            (item for item in EMPLOYEE_TEMPLATES if item.code == code),
            None,
        )
        if builtin is not None:
            return builtin
        managed = self.session.scalar(
            select(DigitalEmployeeManagedTemplate).where(
                DigitalEmployeeManagedTemplate.business_unit_id
                == business_unit_id,
                DigitalEmployeeManagedTemplate.code == code,
                DigitalEmployeeManagedTemplate.status == "PUBLISHED",
            )
        )
        if managed is None:
            raise ApiProblem(
                status_code=404,
                code="EMPLOYEE_TEMPLATE_NOT_FOUND",
                title="Employee template not found",
                detail=f"Employee template '{code}' is not published.",
            )
        return _managed_employee_template(managed)

    def list_revisions(
        self,
        employee_id: UUID,
    ) -> list[DigitalEmployeeRevisionView]:
        self.get(employee_id)
        rows = self.session.scalars(
            select(DigitalEmployeeRevision)
            .where(DigitalEmployeeRevision.employee_id == employee_id)
            .order_by(DigitalEmployeeRevision.revision.desc())
        ).all()
        return [
            DigitalEmployeeRevisionView(
                id=row.id,
                employee_id=row.employee_id,
                revision=row.revision,
                status=row.status,
                manifest=row.manifest_json,
                instruction=row.instruction_text,
                change_note=row.change_note,
                created_by=row.created_by,
                created_at=row.created_at,
                published_at=row.published_at,
            )
            for row in rows
        ]

    def activate_trial(
        self,
        employee_id: UUID,
        *,
        actor_id: str,
    ) -> DigitalEmployee:
        employee = self.get(employee_id)
        if employee.status not in {
            "TRIAL",
            "EVALUATION_FAILED",
            "DISABLED",
        }:
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_NOT_IN_TRIAL",
                title="Employee is not in trial",
                detail=f"Employee status is {employee.status}.",
            )
        evaluation = self.evaluate_resources(employee)
        passed = bool(evaluation["passed"])
        employee.activation_evaluation_json = evaluation
        employee.activation_evaluated_at = datetime.now(UTC)
        if passed:
            employee.status = "ACTIVE"
            employee.config_revision += 1
            self._add_revision(
                employee,
                actor_id=actor_id,
                change_note="Activated after trial evaluation",
            )
        else:
            employee.status = "EVALUATION_FAILED"
        self.session.commit()
        self.session.refresh(employee)
        return employee

    def invalidate_activation_if_changed(
        self,
        employee: DigitalEmployee,
        *,
        actor_id: str,
        note: str,
        require_baseline: bool = False,
    ) -> bool:
        evaluation = self.evaluate_resources(employee)
        previous_hash = employee.activation_evaluation_json.get(
            "resource_hash"
        )
        if (
            not isinstance(previous_hash, str)
            and employee.manifest_json.get("activation_required") is not True
            and not require_baseline
        ):
            return False
        hash_unchanged = (
            isinstance(previous_hash, str)
            and previous_hash == evaluation["resource_hash"]
        )
        if hash_unchanged and (
            employee.status != "ACTIVE"
            or evaluation["passed"] is True
        ):
            return False
        if employee.status == "ACTIVE":
            employee.status = "TRIAL"
        employee.activation_evaluation_json = evaluation
        employee.activation_evaluated_at = datetime.now(UTC)
        employee.config_revision += 1
        self._add_revision(
            employee,
            actor_id=actor_id,
            change_note=note,
            status=_revision_status(employee),
        )
        return True

    def evaluate_resources(
        self,
        employee: DigitalEmployee,
    ) -> dict[str, object]:
        from ticket_agent.agent_skills.models import (
            AgentSkill,
            DigitalEmployeeSkillBinding,
        )

        skill_rows = self.session.execute(
            select(AgentSkill.code, AgentSkill.version)
            .join(
                DigitalEmployeeSkillBinding,
                DigitalEmployeeSkillBinding.skill_id == AgentSkill.id,
            )
            .where(
                DigitalEmployeeSkillBinding.employee_id == employee.id,
                DigitalEmployeeSkillBinding.enabled.is_(True),
                AgentSkill.business_unit_id == employee.business_unit_id,
                AgentSkill.status == "ACTIVE",
            )
        ).all()
        skill_codes = {str(code) for code, _version in skill_rows}
        knowledge_ids = {
            str(value)
            for value in self.session.scalars(
                select(DigitalEmployeeKnowledgeBinding.knowledge_space_id)
                .join(
                    KnowledgeSpace,
                    KnowledgeSpace.id
                    == DigitalEmployeeKnowledgeBinding.knowledge_space_id,
                )
                .where(
                    DigitalEmployeeKnowledgeBinding.employee_id
                    == employee.id,
                    DigitalEmployeeKnowledgeBinding.enabled.is_(True),
                    KnowledgeSpace.business_unit_id
                    == employee.business_unit_id,
                    KnowledgeSpace.status == "ACTIVE",
                )
            ).all()
        }
        mcp_rows = self.session.execute(
            select(
                DigitalEmployeeMcpBinding.connector_id,
                DigitalEmployeeMcpBinding.allowed_tools_json,
                McpConnector.tools_json,
            )
            .join(
                McpConnector,
                McpConnector.id == DigitalEmployeeMcpBinding.connector_id,
            )
            .where(
                DigitalEmployeeMcpBinding.employee_id == employee.id,
                DigitalEmployeeMcpBinding.enabled.is_(True),
                McpConnector.business_unit_id == employee.business_unit_id,
                McpConnector.status == "ACTIVE",
            )
        ).all()
        actual_mcp = {
            str(connector_id): (
                _string_set(allowed_tools)
                & _discovered_mcp_tool_names(discovered_tools)
            )
            for connector_id, allowed_tools, discovered_tools in mcp_rows
        }
        required = employee.manifest_json.get("required_resources", {})
        if not isinstance(required, dict):
            required = {}
        required_skill_codes = _string_set(required.get("skill_codes"))
        required_knowledge_ids = _string_set(
            required.get("knowledge_space_ids")
        )
        required_mcp = _required_mcp_mapping(
            required.get("mcp_tools")
        )
        capability_text = " ".join(
            str(item)
            for item in employee.manifest_json.get("capabilities", [])
        )
        requires_live = any(
            term in capability_text
            for term in ("物流", "仓储", "订单", "实时")
        )
        checks = [
            _activation_check(
                "employee",
                "员工状态",
                employee.status
                in {
                    "TRIAL",
                    "ACTIVE",
                    "EVALUATION_FAILED",
                    "DISABLED",
                },
                f"员工状态为 {employee.status}。",
            ),
            _activation_check(
                "tools",
                "工具权限",
                bool(employee.tool_allowlist_json),
                f"允许工具数：{len(employee.tool_allowlist_json)}。",
            ),
            _activation_check(
                "skills",
                "Skill / SOP",
                (
                    required_skill_codes.issubset(skill_codes)
                    if required_skill_codes
                    else bool(skill_codes)
                ),
                _resource_detail(
                    required_skill_codes,
                    skill_codes,
                    "Skill",
                ),
            ),
            _activation_check(
                "knowledge",
                "知识库",
                (
                    required_knowledge_ids.issubset(knowledge_ids)
                    if required_knowledge_ids
                    else bool(knowledge_ids)
                ),
                _resource_detail(
                    required_knowledge_ids,
                    knowledge_ids,
                    "知识空间",
                ),
            ),
        ]
        mcp_missing = _missing_mcp_resources(
            required_mcp,
            actual_mcp,
        )
        if required_mcp or requires_live:
            checks.append(
                _activation_check(
                    "mcp",
                    "实时业务工具",
                    (
                        not mcp_missing
                        if required_mcp
                        else any(actual_mcp.values())
                    ),
                    (
                        "缺少 MCP 或工具："
                        + "、".join(mcp_missing)
                        if mcp_missing
                        else f"可用 MCP 数：{len(actual_mcp)}。"
                    ),
                )
            )
        snapshot: dict[str, object] = {
            "workflow_key": employee.workflow_key,
            "required_resources": {
                "skill_codes": sorted(required_skill_codes),
                "knowledge_space_ids": sorted(required_knowledge_ids),
                "mcp_tools": {
                    connector_id: sorted(tools)
                    for connector_id, tools in sorted(
                        required_mcp.items()
                    )
                },
            },
            "tool_allowlist": sorted(
                {
                    str(tool)
                    for tool in employee.tool_allowlist_json
                    if isinstance(tool, str)
                }
            ),
            "model_profile": employee.model_profile_json,
            "knowledge_policy": employee.knowledge_policy_json,
            "skills": {
                str(code): int(version)
                for code, version in sorted(skill_rows)
            },
            "knowledge_space_ids": sorted(knowledge_ids),
            "mcp_tools": {
                connector_id: sorted(tools)
                for connector_id, tools in sorted(actual_mcp.items())
            },
        }
        encoded = json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return {
            "passed": all(
                check["status"] == "PASSED" for check in checks
            ),
            "checks": checks,
            "resource_hash": hashlib.sha256(encoded).hexdigest(),
            "resources": snapshot,
        }

    def get_route_rule(
        self,
        employee_id: UUID,
    ) -> DigitalEmployeeRouteRuleView:
        self.get(employee_id)
        rule = self.session.scalar(
            select(DigitalEmployeeRouteRule).where(
                DigitalEmployeeRouteRule.employee_id == employee_id
            )
        )
        if rule is None:
            raise ApiProblem(
                status_code=404,
                code="EMPLOYEE_ROUTE_RULE_NOT_FOUND",
                title="Employee route rule not found",
                detail="Create a route rule before using automatic employee routing.",
            )
        return self._route_rule_view(rule)

    def list_route_rules(
        self,
        business_unit_id: str,
    ) -> list[DigitalEmployeeRouteRuleView]:
        rows = list(
            self.session.scalars(
                select(DigitalEmployeeRouteRule)
                .where(
                    DigitalEmployeeRouteRule.business_unit_id
                    == business_unit_id
                )
                .order_by(
                    DigitalEmployeeRouteRule.priority,
                    DigitalEmployeeRouteRule.created_at,
                )
            ).all()
        )
        return [self._route_rule_view(rule) for rule in rows]

    def update_route_rule(
        self,
        employee_id: UUID,
        payload: DigitalEmployeeRouteRuleUpdate,
    ) -> DigitalEmployeeRouteRuleView:
        employee = self.get_for_update(employee_id)
        rule = self.session.scalar(
            select(DigitalEmployeeRouteRule).where(
                DigitalEmployeeRouteRule.employee_id == employee_id
            )
        )
        if rule is None:
            rule = DigitalEmployeeRouteRule(
                business_unit_id=employee.business_unit_id,
                employee_id=employee.id,
            )
            self.session.add(rule)
        rule.intents_json = payload.intents
        rule.categories_json = payload.categories
        rule.channels_json = payload.channels
        rule.priority = payload.priority
        rule.fallback = payload.fallback
        rule.enabled = payload.enabled
        self.session.commit()
        self.session.refresh(rule)
        return self._route_rule_view(rule)

    def list_route_decisions(
        self,
        *,
        business_unit_id: str,
        limit: int,
    ) -> DigitalEmployeeRouteDecisionList:
        total = self.session.scalar(
            select(func.count())
            .select_from(DigitalEmployeeRouteDecision)
            .where(
                DigitalEmployeeRouteDecision.business_unit_id
                == business_unit_id
            )
        ) or 0
        rows = list(
            self.session.scalars(
                select(DigitalEmployeeRouteDecision)
                .where(
                    DigitalEmployeeRouteDecision.business_unit_id
                    == business_unit_id
                )
                .order_by(DigitalEmployeeRouteDecision.created_at.desc())
                .limit(limit)
            ).all()
        )
        return DigitalEmployeeRouteDecisionList(
            items=[
                DigitalEmployeeRouteDecisionView(
                    id=row.id,
                    business_unit_id=row.business_unit_id,
                    ticket_id=row.ticket_id,
                    conversation_id=row.conversation_id,
                    selected_employee_id=row.selected_employee_id,
                    selected_employee_key=row.selected_employee_key,
                    candidates=row.candidates_json,
                    reason_code=row.reason_code,
                    reason=row.reason,
                    score=row.score,
                    confidence=row.confidence,
                    created_at=row.created_at,
                )
                for row in rows
            ],
            total=int(total),
        )

    def _add_revision(
        self,
        employee: DigitalEmployee,
        *,
        actor_id: str,
        change_note: str,
        status: str = "PUBLISHED",
    ) -> None:
        self.session.add(
            DigitalEmployeeRevision(
                employee_id=employee.id,
                revision=employee.config_revision,
                status=status,
                manifest_json=employee.manifest_json,
                instruction_text=employee.instruction_text,
                change_note=change_note[:500],
                created_by=actor_id,
                published_at=(
                    datetime.now(UTC)
                    if status == "PUBLISHED"
                    else None
                ),
            )
        )

    def _add_route_rule(
        self,
        employee: DigitalEmployee,
        *,
        intents: list[str],
        fallback: bool,
    ) -> None:
        self.session.add(
            DigitalEmployeeRouteRule(
                business_unit_id=employee.business_unit_id,
                employee_id=employee.id,
                intents_json=intents,
                categories_json=[],
                channels_json=[],
                priority=100,
                fallback=fallback,
                enabled=True,
            )
        )

    @staticmethod
    def _route_rule_view(
        rule: DigitalEmployeeRouteRule,
    ) -> DigitalEmployeeRouteRuleView:
        return DigitalEmployeeRouteRuleView(
            id=rule.id,
            business_unit_id=rule.business_unit_id,
            employee_id=rule.employee_id,
            intents=[str(item) for item in rule.intents_json],
            categories=[str(item) for item in rule.categories_json],
            channels=[str(item) for item in rule.channels_json],
            priority=rule.priority,
            fallback=rule.fallback,
            enabled=rule.enabled,
            updated_at=rule.updated_at,
        )

    def _bind_template_resources(
        self,
        employee: DigitalEmployee,
        template: EmployeeTemplate,
        *,
        knowledge_space_ids: list[UUID],
        skill_ids: list[UUID],
        mcp_connector_ids: list[UUID],
        commit: bool = True,
    ) -> None:
        if knowledge_space_ids:
            spaces = list(
                self.session.scalars(
                    select(KnowledgeSpace).where(
                        KnowledgeSpace.id.in_(knowledge_space_ids)
                    )
                ).all()
            )
            if len(spaces) != len(set(knowledge_space_ids)):
                raise ApiProblem(
                    status_code=422,
                    code="KNOWLEDGE_SPACE_NOT_FOUND",
                    title="Knowledge space not found",
                    detail="One or more knowledge spaces do not exist.",
                )
            if any(
                space.business_unit_id != employee.business_unit_id
                for space in spaces
            ):
                raise ApiProblem(
                    status_code=422,
                    code="KNOWLEDGE_SPACE_UNIT_MISMATCH",
                    title="Knowledge space belongs to another unit",
                    detail="Employee and knowledge space must share a business unit.",
                )
            for space in spaces:
                self.session.add(
                    DigitalEmployeeKnowledgeBinding(
                        employee_id=employee.id,
                        knowledge_space_id=space.id,
                        workflow_key=template.workflow_key,
                        scope_json={},
                        enabled=True,
                    )
                )
        self._bind_template_skill_mcp_resources(
            employee,
            template,
            skill_ids=skill_ids,
            mcp_connector_ids=mcp_connector_ids,
            commit=commit,
        )

    def _bind_template_skill_mcp_resources(
        self,
        employee: DigitalEmployee,
        template: EmployeeTemplate,
        *,
        skill_ids: list[UUID],
        mcp_connector_ids: list[UUID],
        commit: bool,
    ) -> None:
        from ticket_agent.agent_skills.models import (
            DigitalEmployeeSkillBinding,
        )
        from ticket_agent.agent_skills.service import AgentSkillService

        skills = AgentSkillService(self.session).list_skills(
            employee.business_unit_id,
            commit=commit,
        )
        selected_skill_ids: set[UUID] = set(skill_ids)
        for skill in skills:
            if (
                skill.code not in template.skill_codes
                and skill.id not in selected_skill_ids
            ):
                continue
            self.session.add(
                DigitalEmployeeSkillBinding(
                    employee_id=employee.id,
                    skill_id=skill.id,
                    enabled=True,
                    priority=100,
                )
            )

        if not mcp_connector_ids:
            return
        connectors = list(
            self.session.scalars(
                select(McpConnector).where(
                    McpConnector.id.in_(mcp_connector_ids)
                )
            ).all()
        )
        if len(connectors) != len(set(mcp_connector_ids)):
            raise ApiProblem(
                status_code=422,
                code="MCP_CONNECTOR_NOT_FOUND",
                title="MCP connector not found",
                detail="One or more MCP connectors do not exist.",
            )
        mcp_policy = {
            str(binding.get("connector_id")): _string_list(
                binding.get("allowed_tools")
            )
            for binding in template.mcp_bindings
        }
        for connector in connectors:
            if connector.business_unit_id != employee.business_unit_id:
                raise ApiProblem(
                    status_code=422,
                    code="MCP_CONNECTOR_UNIT_MISMATCH",
                    title="MCP connector belongs to another unit",
                    detail="Employee and connector must share a business unit.",
                )
            self.session.add(
                DigitalEmployeeMcpBinding(
                    employee_id=employee.id,
                    connector_id=connector.id,
                    enabled=True,
                    allowed_tools_json=[
                        str(tool.get("name"))
                        for tool in connector.tools_json
                        if isinstance(tool.get("name"), str)
                        and tool.get("is_write") is not True
                    ]
                    if str(connector.id) not in mcp_policy
                    else mcp_policy[str(connector.id)],
                    write_approved=False,
                )
            )

    def _validate_template_resources(
        self,
        template: EmployeeTemplate,
        *,
        business_unit_id: str,
    ) -> None:
        from ticket_agent.agent_skills.models import AgentSkill

        required_skills = set(template.skill_codes)
        active_skills = set(
            self.session.scalars(
                select(AgentSkill.code).where(
                    AgentSkill.business_unit_id == business_unit_id,
                    AgentSkill.code.in_(required_skills),
                    AgentSkill.status == "ACTIVE",
                )
            ).all()
        )
        missing_skills = sorted(required_skills - active_skills)
        if missing_skills:
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_TEMPLATE_SKILL_UNAVAILABLE",
                title="Template Skill is unavailable",
                detail=(
                    "Template requires unavailable Skills: "
                    + "、".join(missing_skills)
                ),
            )
        required_knowledge = set(
            _binding_uuid_values(
                template.knowledge_bindings,
                "knowledge_space_id",
            )
        )
        active_knowledge = set(
            self.session.scalars(
                select(KnowledgeSpace.id).where(
                    KnowledgeSpace.id.in_(required_knowledge),
                    KnowledgeSpace.business_unit_id == business_unit_id,
                    KnowledgeSpace.status == "ACTIVE",
                )
            ).all()
        )
        missing_knowledge = sorted(
            str(value)
            for value in required_knowledge - active_knowledge
        )
        if missing_knowledge:
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_TEMPLATE_KNOWLEDGE_UNAVAILABLE",
                title="Template knowledge is unavailable",
                detail=(
                    "Template requires unavailable knowledge spaces: "
                    + "、".join(missing_knowledge)
                ),
            )
        required_connectors = set(
            _binding_uuid_values(
                template.mcp_bindings,
                "connector_id",
            )
        )
        connectors = {
            connector.id: connector
            for connector in self.session.scalars(
                select(McpConnector).where(
                    McpConnector.id.in_(required_connectors),
                    McpConnector.business_unit_id == business_unit_id,
                    McpConnector.status == "ACTIVE",
                )
            ).all()
        }
        missing_mcp = sorted(
            str(value)
            for value in required_connectors - set(connectors)
        )
        if missing_mcp:
            raise ApiProblem(
                status_code=409,
                code="EMPLOYEE_TEMPLATE_MCP_UNAVAILABLE",
                title="Template MCP is unavailable",
                detail=(
                    "Template requires unavailable MCP connectors: "
                    + "、".join(missing_mcp)
                ),
            )
        for binding in template.mcp_bindings:
            connector_id = binding.get("connector_id")
            if not isinstance(connector_id, str):
                continue
            connector = connectors.get(UUID(connector_id))
            if connector is None:
                continue
            available_tools = _discovered_mcp_tool_names(
                connector.tools_json
            )
            missing_tools = (
                _string_set(binding.get("allowed_tools"))
                - available_tools
            )
            if missing_tools:
                raise ApiProblem(
                    status_code=409,
                    code="EMPLOYEE_TEMPLATE_MCP_TOOL_UNAVAILABLE",
                    title="Template MCP tool is unavailable",
                    detail=(
                        f"MCP {connector.code} does not expose: "
                        + "、".join(sorted(missing_tools))
                    ),
                )

    def view(self, employee: DigitalEmployee) -> DigitalEmployeeView:
        return DigitalEmployeeView(
            id=employee.id,
            employee_key=employee.employee_key,
            name=employee.name,
            version=employee.version,
            scenario_type=employee.scenario_type,
            domain=employee.domain,
            template_code=employee.template_code,
            workflow_key=employee.workflow_key,
            business_unit_id=employee.business_unit_id,
            service_identity=employee.service_identity,
            status=employee.status,
            handoff_queue=employee.handoff_queue,
            knowledge_policy=employee.knowledge_policy_json,
            model_profile=employee.model_profile_json,
            tool_allowlist=employee.tool_allowlist_json,
            instruction=employee.instruction_text,
            manifest=employee.manifest_json,
            activation_evaluation=employee.activation_evaluation_json,
            activation_evaluated_at=employee.activation_evaluated_at,
            config_revision=employee.config_revision,
            created_at=employee.created_at,
            updated_at=employee.updated_at,
        )

    @staticmethod
    def _validate_workflow(workflow_key: str) -> None:
        if workflow_key not in SUPPORTED_WORKFLOW_KEYS:
            raise ApiProblem(
                status_code=422,
                code="UNSUPPORTED_WORKFLOW",
                title="Unsupported workflow",
                detail=f"Workflow '{workflow_key}' is not registered.",
            )


def _managed_template_view(
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


def _managed_employee_template(
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


def _binding_uuid_values(
    bindings: list[dict[str, object]],
    key: str,
) -> list[UUID]:
    values: list[UUID] = []
    for binding in bindings:
        raw = binding.get(key)
        if isinstance(raw, str):
            values.append(UUID(raw))
    return values


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]


def _string_list_or(
    value: object,
    fallback: list[str],
) -> list[str]:
    if not isinstance(value, list):
        return list(fallback)
    return [str(item) for item in value if isinstance(item, str)]


def _string_set(value: object) -> set[str]:
    return set(_string_list(value))


def _discovered_mcp_tool_names(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {
        str(tool.get("name"))
        for tool in value
        if isinstance(tool, dict)
        and isinstance(tool.get("name"), str)
    }


def _required_mcp_mapping(value: object) -> dict[str, set[str]]:
    if not isinstance(value, list):
        return {}
    required: dict[str, set[str]] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        connector_id = item.get("connector_id")
        if not isinstance(connector_id, str):
            continue
        required[connector_id] = _string_set(
            item.get("allowed_tools")
        )
    return required


def _missing_mcp_resources(
    required: dict[str, set[str]],
    actual: dict[str, set[str]],
) -> list[str]:
    missing: list[str] = []
    for connector_id, required_tools in required.items():
        actual_tools = actual.get(connector_id)
        if actual_tools is None:
            missing.append(f"{connector_id}(未绑定或不可用)")
            continue
        missing_tools = required_tools - actual_tools
        if missing_tools:
            missing.append(
                f"{connector_id}:"
                + "、".join(sorted(missing_tools))
            )
    return missing


def _resource_detail(
    required: set[str],
    actual: set[str],
    label: str,
) -> str:
    missing = required - actual
    if missing:
        return f"缺少{label}：" + "、".join(sorted(missing))
    return f"启用{label}数：{len(actual)}。"


def _activation_check(
    key: str,
    label: str,
    passed: bool,
    detail: str,
) -> dict[str, str]:
    return {
        "key": key,
        "label": label,
        "status": "PASSED" if passed else "FAILED",
        "detail": detail,
    }


def _domain_for_workflow(workflow_key: str) -> str:
    return (
        "human_resources"
        if workflow_key.startswith("hr_")
        else "customer_service"
    )


def _revision_status(employee: DigitalEmployee) -> str:
    if employee.status == "ACTIVE":
        return "PUBLISHED"
    return employee.status


def _manifest(
    *,
    domain: str,
    template_code: str | None,
    capabilities: list[str],
    intents: list[str],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "domain": domain,
        "template_code": template_code,
        "capabilities": capabilities,
        "intents": intents,
        "routing": {
            "deterministic_first": True,
            "llm_fallback_only": True,
        },
    }


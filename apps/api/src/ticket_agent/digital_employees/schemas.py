from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class DigitalEmployeeCreate(BaseModel):
    employee_key: str = Field(
        min_length=3,
        max_length=100,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(default="1.0.0", max_length=32)
    scenario_type: str = Field(min_length=1, max_length=64)
    workflow_key: str = Field(min_length=1, max_length=100)
    business_unit_id: str = Field(min_length=1, max_length=64)
    service_identity: str = Field(min_length=1, max_length=160)
    handoff_queue: str = Field(default="MANUAL_TRIAGE", max_length=64)
    knowledge_policy: dict[str, Any] = Field(default_factory=dict)
    model_profile: dict[str, Any] = Field(default_factory=dict)
    tool_allowlist: list[str] = Field(default_factory=list)
    instruction: str = Field(default="", max_length=4000)


class DigitalEmployeeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    version: str | None = Field(default=None, max_length=32)
    scenario_type: str | None = Field(default=None, min_length=1, max_length=64)
    workflow_key: str | None = Field(default=None, min_length=1, max_length=100)
    service_identity: str | None = Field(default=None, min_length=1, max_length=160)
    status: Literal["ACTIVE", "DISABLED"] | None = None
    handoff_queue: str | None = Field(default=None, max_length=64)
    knowledge_policy: dict[str, Any] | None = None
    model_profile: dict[str, Any] | None = None
    tool_allowlist: list[str] | None = None
    instruction: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def require_change(self) -> "DigitalEmployeeUpdate":
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("at least one field must be provided")
        return self


class DigitalEmployeeConfigurationKnowledgeBinding(BaseModel):
    knowledge_space_id: UUID
    workflow_key: str | None = Field(default=None, max_length=100)
    scope: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class DigitalEmployeeConfigurationSkillBinding(BaseModel):
    skill_id: UUID
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=1000)


class DigitalEmployeeConfigurationMcpBinding(BaseModel):
    connector_id: UUID
    enabled: bool = True
    allowed_tools: list[str] = Field(default_factory=list, max_length=100)
    write_approved: bool = False


class DigitalEmployeeConfigurationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal["ACTIVE", "DISABLED"] | None = None
    handoff_queue: str | None = Field(default=None, max_length=64)
    knowledge_policy: dict[str, Any] | None = None
    model_profile: dict[str, Any] | None = None
    tool_allowlist: list[str] | None = Field(default=None, max_length=50)
    instruction: str | None = Field(default=None, max_length=4000)
    knowledge_bindings: (
        list[DigitalEmployeeConfigurationKnowledgeBinding] | None
    ) = Field(default=None, max_length=100)
    skill_bindings: (
        list[DigitalEmployeeConfigurationSkillBinding] | None
    ) = Field(default=None, max_length=100)
    mcp_bindings: (
        list[DigitalEmployeeConfigurationMcpBinding] | None
    ) = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def require_change(self) -> "DigitalEmployeeConfigurationUpdate":
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("at least one field must be provided")
        return self


class DigitalEmployeeView(BaseModel):
    id: UUID
    employee_key: str
    name: str
    version: str
    scenario_type: str
    domain: str
    template_code: str | None
    workflow_key: str
    business_unit_id: str
    service_identity: str
    status: str
    handoff_queue: str
    knowledge_policy: dict[str, Any]
    model_profile: dict[str, Any]
    tool_allowlist: list[str]
    instruction: str = ""
    manifest: dict[str, Any]
    activation_evaluation: dict[str, Any]
    activation_evaluated_at: datetime | None
    config_revision: int
    created_at: datetime
    updated_at: datetime


class DigitalEmployeeFromTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    template_code: str = Field(min_length=2, max_length=100)
    business_unit_id: str = Field(default="bu_demo", min_length=1, max_length=64)
    knowledge_space_ids: list[UUID] = Field(default_factory=list)
    skill_ids: list[UUID] = Field(default_factory=list)
    mcp_connector_ids: list[UUID] = Field(default_factory=list)
    model_profile: dict[str, Any] = Field(default_factory=dict)
    instruction: str = Field(default="", max_length=4000)
    change_note: str = Field(default="", max_length=500)


class DigitalEmployeeTemplateView(BaseModel):
    id: UUID | None = None
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
    status: str = "PUBLISHED"
    builtin: bool = True
    source_draft_id: UUID | None = None
    version: int = 1
    published_at: datetime | None = None
    knowledge_bindings: list[dict[str, Any]] = Field(default_factory=list)
    mcp_bindings: list[dict[str, Any]] = Field(default_factory=list)
    model_profile: dict[str, Any] = Field(default_factory=dict)
    knowledge_policy: dict[str, Any] = Field(default_factory=dict)
    readiness_snapshot: dict[str, Any] = Field(default_factory=dict)


class ManagedEmployeeTemplateReview(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    note: str = Field(default="", max_length=2000)


class ManagedEmployeeTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    capabilities: list[str] | None = Field(default=None, max_length=100)
    intents: list[str] | None = Field(default=None, max_length=100)
    skill_codes: list[str] | None = Field(default=None, max_length=100)
    tool_allowlist: list[str] | None = Field(default=None, max_length=100)
    knowledge_bindings: list[dict[str, Any]] | None = None
    mcp_bindings: list[dict[str, Any]] | None = None

    @model_validator(mode="after")
    def require_change(self) -> "ManagedEmployeeTemplateUpdate":
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("at least one field must be provided")
        return self


class ManagedEmployeeTemplateRevisionView(BaseModel):
    id: UUID
    template_id: UUID
    revision: int
    status: str
    snapshot: dict[str, Any]
    change_note: str
    created_by: str
    published_at: datetime | None
    created_at: datetime


class DigitalEmployeeRevisionView(BaseModel):
    id: UUID
    employee_id: UUID
    revision: int
    status: str
    manifest: dict[str, Any]
    instruction: str = ""
    change_note: str
    created_by: str
    created_at: datetime
    published_at: datetime | None


class DigitalEmployeeRouteRuleView(BaseModel):
    id: UUID
    business_unit_id: str
    employee_id: UUID
    intents: list[str]
    categories: list[str]
    channels: list[str]
    priority: int
    fallback: bool
    enabled: bool
    updated_at: datetime


class DigitalEmployeeRouteRuleUpdate(BaseModel):
    intents: list[str] = Field(default_factory=list, max_length=100)
    categories: list[str] = Field(default_factory=list, max_length=100)
    channels: list[str] = Field(default_factory=list, max_length=20)
    priority: int = Field(default=100, ge=0, le=1000)
    fallback: bool = False
    enabled: bool = True


class DigitalEmployeeRouteDecisionView(BaseModel):
    id: UUID
    business_unit_id: str
    ticket_id: UUID | None
    conversation_id: UUID | None
    selected_employee_id: UUID
    selected_employee_key: str
    candidates: list[dict[str, Any]]
    reason_code: str
    reason: str
    score: float
    confidence: float
    created_at: datetime


class DigitalEmployeeRouteDecisionList(BaseModel):
    items: list[DigitalEmployeeRouteDecisionView]
    total: int


class DigitalEmployeeRouteIntentConflict(BaseModel):
    term: str
    employee_ids: list[UUID]
    employee_names: list[str]
    entry_ids: list[UUID]
    entry_names: list[str]
    source: Literal["EXPLICIT", "INHERITED", "MIXED"]


class DigitalEmployeeRouteIntentSuppression(BaseModel):
    term: str
    affected_employee_ids: list[UUID]
    affected_employee_names: list[str]
    owner_employee_ids: list[UUID]
    owner_employee_names: list[str]
    entry_ids: list[UUID]
    entry_names: list[str]


class DigitalEmployeeRouteIntentConflictList(BaseModel):
    business_unit_id: str
    active_employee_count: int
    checked_terms: int
    conflicts: list[DigitalEmployeeRouteIntentConflict]
    suppressed: list[DigitalEmployeeRouteIntentSuppression]


class DigitalEmployeeRouteEvaluationCaseCreate(BaseModel):
    service_entry_id: UUID
    expected_employee_id: UUID
    question: str = Field(min_length=2, max_length=1000)
    notes: str = Field(default="", max_length=1000)
    enabled: bool = True


class DigitalEmployeeRouteEvaluationCaseUpdate(BaseModel):
    expected_employee_id: UUID | None = None
    question: str | None = Field(
        default=None,
        min_length=2,
        max_length=1000,
    )
    notes: str | None = Field(default=None, max_length=1000)
    enabled: bool | None = None


class DigitalEmployeeRouteEvaluationCaseView(BaseModel):
    id: UUID
    business_unit_id: str
    service_entry_id: UUID
    expected_employee_id: UUID
    expected_employee_name: str
    question: str
    notes: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class DigitalEmployeeRouteEvaluationResultView(BaseModel):
    case_id: UUID
    question: str
    expected_employee_id: UUID
    expected_employee_name: str
    predicted_employee_id: UUID
    predicted_employee_name: str
    matched: bool
    reason_code: str
    confidence: float
    candidates: list[dict[str, Any]]


class DigitalEmployeeRouteEvaluationRunRequest(BaseModel):
    service_entry_id: UUID


class DigitalEmployeeRouteEvaluationRunView(BaseModel):
    id: UUID
    business_unit_id: str
    service_entry_id: UUID | None
    total: int
    passed: int
    failed: int
    accuracy: float
    results: list[DigitalEmployeeRouteEvaluationResultView]
    created_by: str
    created_at: datetime


class DigitalEmployeeRouteEvaluationRunList(BaseModel):
    items: list[DigitalEmployeeRouteEvaluationRunView]
    total: int


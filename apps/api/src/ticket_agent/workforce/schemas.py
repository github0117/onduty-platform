from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class WorkforceTaskCreate(BaseModel):
    business_unit_id: str = Field(default="bu_demo", min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=20_000)
    context: dict[str, Any] = Field(default_factory=dict)
    supervisor_employee_id: UUID | None = None


class WorkforceReadinessCheckView(BaseModel):
    key: str
    label: str
    status: Literal["READY", "WARNING", "BLOCKED", "NOT_APPLICABLE"]
    detail: str


class WorkforceEmployeeReadinessView(BaseModel):
    employee_id: UUID
    employee_key: str
    employee_name: str
    template_code: str | None
    step_sequences: list[int]
    status: Literal["READY", "DEGRADED", "BLOCKED"]
    checks: list[WorkforceReadinessCheckView]


class WorkforceCapabilityGapView(BaseModel):
    step_id: UUID | None
    sequence: int | None
    step_title: str
    required_capability: str
    assigned_employee_name: str
    reason: str
    recommended_template_code: str | None
    recommended_template_name: str
    recommended_domain: str
    recommended_workflow_key: str
    recommended_capabilities: list[str]
    recommended_intents: list[str]
    recommended_skills: list[str]
    recommended_tools: list[str]
    status: Literal["DRAFT_ONLY"] = "DRAFT_ONLY"
    approval_required: bool = True


class WorkforceTaskStepView(BaseModel):
    id: UUID
    sequence: int
    title: str
    instructions: str
    assigned_employee_id: UUID
    assigned_employee_key: str
    assigned_employee_name: str
    route_decision_id: UUID | None
    required_capability: str | None = None
    route_reason_code: str | None = None
    route_reason: str | None = None
    route_confidence: float | None = None
    route_candidates: list[dict[str, Any]] = Field(default_factory=list)
    status: str
    output: dict[str, Any]
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class WorkforceTaskView(BaseModel):
    id: UUID
    business_unit_id: str
    title: str
    objective: str
    context: dict[str, Any]
    supervisor_employee_id: UUID | None
    supervisor_employee_name: str | None
    status: str
    result_summary: str | None
    created_by: str
    steps: list[WorkforceTaskStepView]
    capability_gaps: list[WorkforceCapabilityGapView]
    employee_readiness: list[WorkforceEmployeeReadinessView]
    capability_assessed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WorkforceTaskList(BaseModel):
    items: list[WorkforceTaskView]
    total: int

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class DigitalEmployeeDraftCreate(BaseModel):
    required_capability: str = Field(min_length=1, max_length=200)
    name: str | None = Field(default=None, min_length=1, max_length=200)


class DigitalEmployeeDraftReview(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    note: str = Field(default="", max_length=2000)


class DigitalEmployeeDraftUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    capabilities: list[str] | None = Field(default=None, max_length=100)
    intents: list[str] | None = Field(default=None, max_length=100)
    skill_codes: list[str] | None = Field(default=None, max_length=100)
    tool_allowlist: list[str] | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def require_change(self) -> "DigitalEmployeeDraftUpdate":
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("at least one field must be provided")
        return self


class DigitalEmployeeDraftView(BaseModel):
    id: UUID
    business_unit_id: str
    source_task_id: UUID | None
    source_step_id: UUID | None
    required_capability: str
    name: str
    template_code: str | None
    domain: str
    workflow_key: str
    scenario_type: str
    handoff_queue: str
    capabilities: list[str]
    intents: list[str]
    skill_codes: list[str]
    tool_allowlist: list[str]
    status: str
    revision: int
    review_note: str | None
    created_by: str
    reviewed_by: str | None
    reviewed_at: datetime | None
    employee_id: UUID | None
    evaluation: dict[str, Any]
    evaluated_at: datetime | None
    published_at: datetime | None
    rolled_back_at: datetime | None
    promoted_template_id: UUID | None
    created_at: datetime
    updated_at: datetime


class DigitalEmployeeDraftList(BaseModel):
    items: list[DigitalEmployeeDraftView]
    total: int


class DigitalEmployeeDraftRevisionView(BaseModel):
    id: UUID
    draft_id: UUID
    revision: int
    status: str
    snapshot: dict[str, Any]
    change_note: str
    created_by: str
    created_at: datetime

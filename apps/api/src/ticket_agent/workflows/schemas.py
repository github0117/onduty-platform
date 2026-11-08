from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class WorkflowStepView(BaseModel):
    id: UUID
    name: str
    status: str
    attempt_count: int
    max_attempts: int
    available_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    last_error: str | None
    output: dict[str, Any] | None


class WorkflowRunView(BaseModel):
    id: UUID
    business_unit_id: str
    workflow_type: str
    aggregate_type: str
    aggregate_id: str
    status: str
    current_step: str | None
    context: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    steps: list[WorkflowStepView] = Field(default_factory=list)


class WorkflowRunList(BaseModel):
    items: list[WorkflowRunView]
    limit: int
    offset: int


class WorkflowReplayResponse(BaseModel):
    accepted: bool
    run: WorkflowRunView

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AgentRunView(BaseModel):
    id: UUID
    business_unit_id: str
    employee_id: UUID
    employee_name: str
    employee_key: str
    ticket_id: UUID | None
    ticket_subject: str | None
    run_type: str
    workflow_key: str
    status: str
    correlation_id: str
    input_summary: dict[str, Any]
    result_summary: dict[str, Any]
    error_code: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None
    duration_ms: int | None


class AgentRunListResponse(BaseModel):
    items: list[AgentRunView]
    total: int


class AgentTraceEvent(BaseModel):
    id: str
    event_type: str
    title: str
    status: str
    timestamp: datetime
    duration_ms: int | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class AgentRunTraceResponse(BaseModel):
    run: AgentRunView
    events: list[AgentTraceEvent]

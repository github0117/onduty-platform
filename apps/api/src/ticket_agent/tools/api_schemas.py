from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ToolCallView(BaseModel):
    id: UUID
    employee_id: UUID
    ticket_id: UUID | None
    tool_key: str
    action_type: str
    risk_level: str
    status: str
    correlation_id: str
    request_payload: dict[str, Any]
    response_summary: dict[str, Any]
    error_code: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None
    duration_ms: float | None


class ToolCallListResponse(BaseModel):
    items: list[ToolCallView]
    total: int


class ToolMetricItem(BaseModel):
    tool_key: str
    calls: int
    succeeded: int
    failed: int
    denied: int
    success_rate: float
    average_duration_ms: float
    p95_duration_ms: float


class ToolMetricsResponse(BaseModel):
    calls: int
    succeeded: int
    failed: int
    denied: int
    success_rate: float
    failure_rate: float
    average_duration_ms: float
    p95_duration_ms: float
    by_tool: list[ToolMetricItem] = Field(default_factory=list)


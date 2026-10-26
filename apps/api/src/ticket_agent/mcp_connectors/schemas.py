from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, model_validator


class McpConnectorCreate(BaseModel):
    business_unit_id: str = Field(default="bu_demo", min_length=1, max_length=64)
    code: str = Field(
        min_length=2,
        max_length=100,
        pattern=r"^[a-z][a-z0-9_-]*$",
    )
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    transport: Literal["streamable_http"] = "streamable_http"
    url: HttpUrl
    header_env: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)
    status: Literal["ACTIVE", "DISABLED"] = "ACTIVE"


class McpConnectorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    url: HttpUrl | None = None
    header_env: dict[str, str] | None = None
    timeout_seconds: float | None = Field(default=None, ge=1, le=300)
    status: Literal["ACTIVE", "DISABLED"] | None = None

    @model_validator(mode="after")
    def require_change(self) -> "McpConnectorUpdate":
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("at least one field must be provided")
        return self


class McpToolView(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    is_write: bool


class McpConnectorView(BaseModel):
    id: UUID
    business_unit_id: str
    code: str
    name: str
    description: str
    transport: str
    url: str
    header_env: dict[str, str]
    timeout_seconds: float
    status: str
    tools: list[McpToolView]
    last_checked_at: datetime | None
    last_check_error: str | None
    created_at: datetime
    updated_at: datetime


class McpHealthView(BaseModel):
    connector_id: UUID
    healthy: bool
    tool_count: int
    tools: list[McpToolView]
    error: str | None
    checked_at: datetime


class EmployeeMcpBindingInput(BaseModel):
    connector_id: UUID
    enabled: bool = True
    allowed_tools: list[str] = Field(default_factory=list)
    write_approved: bool = False


class EmployeeMcpBindingReplace(BaseModel):
    bindings: list[EmployeeMcpBindingInput] = Field(default_factory=list)


class EmployeeMcpBindingView(BaseModel):
    id: UUID
    employee_id: UUID
    connector_id: UUID
    connector_code: str
    connector_name: str
    enabled: bool
    allowed_tools: list[str]
    write_approved: bool


class McpToolApprovalView(BaseModel):
    id: UUID
    business_unit_id: str
    employee_id: UUID
    connector_id: UUID
    ticket_id: UUID | None
    conversation_id: UUID | None
    tool_id: str
    connector_code: str
    tool_name: str
    arguments: dict[str, Any]
    required_role: str
    policy: dict[str, Any]
    status: str
    requested_by: str
    request_correlation_id: str
    reason: str
    decided_by: str | None
    decision_note: str | None
    result: dict[str, Any]
    error_code: str | None
    error_message: str | None
    version: int
    decided_at: datetime | None
    execution_started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class McpToolApprovalList(BaseModel):
    items: list[McpToolApprovalView]
    total: int


class McpToolApprovalDecision(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    expected_version: int = Field(ge=1)
    note: str = Field(default="", max_length=2000)


class McpActionIncidentView(BaseModel):
    id: UUID
    business_unit_id: str
    approval_id: UUID
    employee_id: UUID
    ticket_id: UUID | None
    conversation_id: UUID | None
    tool_id: str
    failure_class: str
    status: str
    error_code: str | None
    error_message: str | None
    required_action: str
    assigned_to: str | None
    resolution_note: str | None
    resolution_outcome: str | None
    reconciliation_status: str
    reconciliation_tool_id: str | None
    reconciliation_arguments: dict[str, Any]
    reconciliation_result: dict[str, Any]
    reconciliation_tool_call_id: UUID | None
    reconciliation_attempts: int
    last_reconciled_at: datetime | None
    compensation_tool_id: str | None
    compensation_approval_id: UUID | None
    compensation_status: str
    compensation_result: dict[str, Any]
    version: int
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class McpActionIncidentList(BaseModel):
    items: list[McpActionIncidentView]
    total: int


class McpActionIncidentAction(BaseModel):
    expected_version: int = Field(ge=1)
    note: str = Field(default="", max_length=4000)


class McpActionIncidentReconcile(BaseModel):
    expected_version: int = Field(ge=1)
    tool_id: str | None = Field(default=None, max_length=200)


class McpActionIncidentResolve(McpActionIncidentAction):
    outcome: Literal[
        "EXECUTED_AS_INTENDED",
        "NOT_EXECUTED",
        "EXECUTED_INCORRECTLY",
        "INCONCLUSIVE",
    ] = "INCONCLUSIVE"


class McpActionIncidentCompensation(BaseModel):
    expected_version: int = Field(ge=1)
    tool_id: str | None = Field(default=None, max_length=200)
    arguments: dict[str, Any] = Field(default_factory=dict)
    note: str = Field(min_length=1, max_length=4000)

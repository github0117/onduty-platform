from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from ticket_agent.connectors.base import find_secret_keys

Direction = Literal["INBOUND", "OUTBOUND", "BIDIRECTIONAL"]
ConnectorType = Literal["email", "http_json"]
ConnectorStatus = Literal["ACTIVE", "DISABLED"]


def _reject_credentials(config: dict[str, Any], field_mapping: dict[str, Any]) -> None:
    paths = find_secret_keys(config) + find_secret_keys(field_mapping)
    if paths:
        raise ValueError(
            "connector config must not contain credentials; "
            f"use secret_ref for {', '.join(paths)}"
        )


def _validate_email(config: dict[str, Any], direction: str) -> None:
    del direction
    if not str(config.get("from_address", "")).strip():
        raise ValueError("email connectors require config.from_address")
    if not str(config.get("imap_host", "")).strip():
        raise ValueError("email connectors require config.imap_host")


def _validate_http(config: dict[str, Any], direction: str) -> None:
    if direction != "INBOUND":
        raise ValueError("http_json connectors are read-only and cannot send outbound")
    if not str(config.get("base_url", "")).strip():
        raise ValueError("http_json connectors require config.base_url")


class ConnectorCreate(BaseModel):
    business_unit_id: str = Field(default="bu_demo", min_length=1, max_length=64)
    connector_key: str = Field(
        min_length=2,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_-]*$",
    )
    name: str = Field(min_length=1, max_length=200)
    connector_type: ConnectorType
    direction: Direction = "BIDIRECTIONAL"
    config: dict[str, Any] = Field(default_factory=dict)
    field_mapping: dict[str, Any] = Field(default_factory=dict)
    secret_ref: str | None = Field(default=None, max_length=200)
    auto_reply_enabled: bool = True
    status: ConnectorStatus = "ACTIVE"

    @model_validator(mode="after")
    def _validate(self) -> "ConnectorCreate":
        _reject_credentials(self.config, self.field_mapping)
        if self.connector_type == "email":
            _validate_email(self.config, self.direction)
        else:
            _validate_http(self.config, self.direction)
        return self


class ConnectorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    direction: Direction | None = None
    config: dict[str, Any] | None = None
    field_mapping: dict[str, Any] | None = None
    secret_ref: str | None = Field(default=None, max_length=200)
    auto_reply_enabled: bool | None = None
    status: ConnectorStatus | None = None
    expected_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _validate(self) -> "ConnectorUpdate":
        if all(
            value is None
            for key, value in self.model_dump().items()
            if key != "expected_version"
        ):
            raise ValueError("at least one field must be provided")
        _reject_credentials(
            self.config or {},
            self.field_mapping or {},
        )
        return self


class ConnectorView(BaseModel):
    id: UUID
    business_unit_id: str
    connector_key: str
    name: str
    connector_type: str
    direction: str
    status: str
    config: dict[str, Any]
    field_mapping: dict[str, Any]
    secret_ref: str | None
    secret_configured: bool
    auto_reply_enabled: bool
    version: int
    last_health_status: str | None
    last_health_at: datetime | None
    last_health_error: str | None
    created_at: datetime
    updated_at: datetime


class ConnectorHealthView(BaseModel):
    connector_id: UUID
    healthy: bool
    detail: str
    metadata: dict[str, Any]
    checked_at: datetime


class ConnectorBindingInput(BaseModel):
    service_entry_id: UUID
    employee_id: UUID | None = None
    allowed_operations: list[str] = Field(default_factory=list)
    write_approved: bool = False


class ConnectorBindingReplace(BaseModel):
    bindings: list[ConnectorBindingInput] = Field(default_factory=list)


class ConnectorBindingView(BaseModel):
    id: UUID
    connector_id: UUID
    service_entry_id: UUID | None
    service_entry_name: str | None
    employee_id: UUID | None
    employee_name: str | None
    allowed_operations: list[str]
    write_approved: bool


class ConnectorInboundPayload(BaseModel):
    message_id: str = Field(min_length=1, max_length=256)
    thread_id: str = Field(min_length=1, max_length=256)
    user_id: str = Field(min_length=1, max_length=256)
    subject: str = Field(default="", max_length=500)
    content: str = Field(min_length=1, max_length=20000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConnectorInboundView(BaseModel):
    id: UUID
    connector_id: UUID
    external_message_id: str
    external_conversation_id: str
    external_user_id: str
    subject: str
    status: str
    attempt_count: int
    conversation_id: UUID | None
    ticket_id: UUID | None
    turn_id: UUID | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    processed_at: datetime | None


class ConnectorOutboundView(BaseModel):
    id: UUID
    connector_id: UUID
    conversation_id: UUID | None
    recipient: str
    subject: str
    status: str
    attempt_count: int
    external_message_id: str | None
    last_error: str | None
    created_at: datetime
    sent_at: datetime | None


class ConnectorMessageList(BaseModel):
    inbound: list[ConnectorInboundView]
    outbound: list[ConnectorOutboundView]


class ConnectorQueryRequest(BaseModel):
    params: dict[str, str] = Field(default_factory=dict)


class ConnectorQueryView(BaseModel):
    connector_id: UUID
    status_code: int
    data: Any

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class BusinessServiceEntryEmployeeInput(BaseModel):
    employee_id: UUID
    role_type: Literal["PRIMARY", "SPECIALIST", "FALLBACK"] = "SPECIALIST"
    priority: int = Field(default=100, ge=0, le=10_000)
    enabled: bool = True


class BusinessServiceEntryCreate(BaseModel):
    business_unit_id: str = Field(default="bu_demo", min_length=1, max_length=64)
    code: str = Field(
        min_length=2,
        max_length=100,
        pattern=r"^[a-z][a-z0-9_-]*$",
    )
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    domain: str = Field(min_length=1, max_length=64)
    channel: str = Field(min_length=1, max_length=64)
    status: Literal["ACTIVE", "DISABLED"] = "ACTIVE"
    default_employee_id: UUID | None = None
    fallback_employee_id: UUID | None = None
    human_queue_id: str = Field(default="MANUAL_TRIAGE", max_length=64)
    knowledge_scope: dict[str, Any] = Field(default_factory=dict)
    sla_policy: dict[str, Any] = Field(default_factory=dict)
    employees: list[BusinessServiceEntryEmployeeInput] = Field(
        default_factory=list
    )


class BusinessServiceEntryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    domain: str | None = Field(default=None, min_length=1, max_length=64)
    channel: str | None = Field(default=None, min_length=1, max_length=64)
    status: Literal["ACTIVE", "DISABLED"] | None = None
    default_employee_id: UUID | None = None
    fallback_employee_id: UUID | None = None
    human_queue_id: str | None = Field(default=None, max_length=64)
    knowledge_scope: dict[str, Any] | None = None
    sla_policy: dict[str, Any] | None = None
    expected_version: int = Field(ge=1)


class BusinessServiceEntryEmployeeView(BaseModel):
    employee_id: UUID
    employee_key: str
    employee_name: str
    role_type: str
    priority: int
    enabled: bool
    employee_status: str


class BusinessServiceEntryView(BaseModel):
    id: UUID
    business_unit_id: str
    code: str
    name: str
    description: str
    domain: str
    channel: str
    status: str
    default_employee_id: UUID | None
    fallback_employee_id: UUID | None
    human_queue_id: str
    knowledge_scope: dict[str, Any]
    sla_policy: dict[str, Any]
    employees: list[BusinessServiceEntryEmployeeView]
    version: int
    created_at: datetime
    updated_at: datetime

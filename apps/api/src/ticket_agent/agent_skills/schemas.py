from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class AgentSkillCreate(BaseModel):
    business_unit_id: str = Field(default="bu_demo", min_length=1, max_length=64)
    code: str = Field(
        min_length=2,
        max_length=100,
        pattern=r"^[a-z][a-z0-9_-]*$",
    )
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    instructions: str = Field(min_length=1, max_length=20_000)
    triggers: list[str] = Field(default_factory=list, max_length=50)
    tools: list[str] = Field(default_factory=list, max_length=50)
    status: Literal["ACTIVE", "DISABLED"] = "ACTIVE"


class AgentSkillUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    instructions: str | None = Field(default=None, min_length=1, max_length=20_000)
    triggers: list[str] | None = Field(default=None, max_length=50)
    tools: list[str] | None = Field(default=None, max_length=50)
    status: Literal["ACTIVE", "DISABLED"] | None = None

    @model_validator(mode="after")
    def require_change(self) -> "AgentSkillUpdate":
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("at least one field must be provided")
        return self


class AgentSkillView(BaseModel):
    id: UUID
    business_unit_id: str
    code: str
    name: str
    description: str
    instructions: str
    triggers: list[str]
    tools: list[str]
    status: str
    version: int
    created_by: str
    created_at: datetime
    updated_at: datetime


class EmployeeSkillBindingInput(BaseModel):
    skill_id: UUID
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=1000)


class EmployeeSkillBindingReplace(BaseModel):
    bindings: list[EmployeeSkillBindingInput] = Field(default_factory=list)


class EmployeeSkillBindingView(BaseModel):
    id: UUID
    employee_id: UUID
    skill_id: UUID
    skill_code: str
    skill_name: str
    enabled: bool
    priority: int

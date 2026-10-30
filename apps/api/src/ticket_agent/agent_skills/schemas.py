from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from ticket_agent.agent_skills.contract import SkillDefinition


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
    # Optional structured contract. Without it the skill still guides the
    # model, but no step can be asserted as complete.
    definition: SkillDefinition | None = None
    status: Literal["ACTIVE", "DISABLED"] = "ACTIVE"


class AgentSkillUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    instructions: str | None = Field(default=None, min_length=1, max_length=20_000)
    triggers: list[str] | None = Field(default=None, max_length=50)
    tools: list[str] | None = Field(default=None, max_length=50)
    definition: SkillDefinition | None = None
    status: Literal["ACTIVE", "DISABLED"] | None = None
    # Optimistic lock: a stale editor gets 409 SKILL_VERSION_CONFLICT instead
    # of silently overwriting another person's change.
    expected_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_change(self) -> "AgentSkillUpdate":
        changes = (
            self.name,
            self.description,
            self.instructions,
            self.triggers,
            self.tools,
            self.definition,
            self.status,
        )
        if all(value is None for value in changes):
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
    definition: dict[str, Any] | None = None
    definition_version: int = 0
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

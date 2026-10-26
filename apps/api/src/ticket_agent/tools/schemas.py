from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class TicketReadInput(BaseModel):
    ticket_id: UUID


class KnowledgeSearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=20_000)
    business_unit_id: str = Field(min_length=1, max_length=64)
    scope: dict[str, str] = Field(default_factory=dict)
    top_k: int | None = Field(default=None, ge=1, le=20)
    min_score: float | None = Field(default=None, ge=0, le=1)


class DraftCreateInput(BaseModel):
    ticket_id: UUID
    text: str = Field(min_length=1, max_length=10_000)
    citation_count: int = Field(ge=0, le=100)
    claim_count: int = Field(ge=0, le=100)


class TicketSyncInput(BaseModel):
    ticket_id: UUID
    external_ticket_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=200)


class EmployeeProfileReadInput(BaseModel):
    employee_id: UUID
    fields: list[str] = Field(default_factory=list, max_length=30)


TOOL_INPUT_MODELS: dict[str, type[BaseModel]] = {
    "ticket.read": TicketReadInput,
    "knowledge.search": KnowledgeSearchInput,
    "draft.create": DraftCreateInput,
    "ticket.sync": TicketSyncInput,
    "employee_profile.read": EmployeeProfileReadInput,
}


def validate_tool_payload(tool_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    model = TOOL_INPUT_MODELS.get(tool_key)
    if model is None:
        raise ValueError(f"No input schema registered for tool '{tool_key}'.")
    return model.model_validate(payload).model_dump(mode="json")


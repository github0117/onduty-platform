from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AssumptionView(BaseModel):
    business_unit_id: str
    currency: str
    hourly_labor_cost: float
    minutes_per_ticket: float
    minutes_per_conversation: float
    minutes_per_listing: float
    version: int
    persisted: bool
    updated_by: str | None = None
    updated_at: datetime | None = None


class AssumptionUpdate(BaseModel):
    currency: str = Field(min_length=3, max_length=8)
    hourly_labor_cost: float = Field(gt=0)
    minutes_per_ticket: float = Field(ge=0)
    minutes_per_conversation: float = Field(ge=0)
    minutes_per_listing: float = Field(ge=0)


class SourceBreakdown(BaseModel):
    source_type: str
    entries: int
    human_minutes_saved: float
    human_hours_saved: float
    labor_cost_saved: float


class EmployeeBreakdown(BaseModel):
    employee_id: UUID | None
    employee_name: str
    entries: int
    human_minutes_saved: float
    human_hours_saved: float
    labor_cost_saved: float


class DailyPoint(BaseModel):
    day: date
    entries: int
    human_minutes_saved: float
    human_hours_saved: float
    labor_cost_saved: float


class EfficiencySummary(BaseModel):
    business_unit_id: str
    days: int
    from_at: datetime
    to_at: datetime
    currency: str
    mixed_currency: bool
    entries: int
    human_minutes_saved: float
    human_hours_saved: float
    labor_cost_saved: float
    model_cost: float
    model_calls: int
    roi: float | None
    net_saving: float
    by_source: list[SourceBreakdown]
    by_employee: list[EmployeeBreakdown]
    daily: list[DailyPoint]
    assumptions: AssumptionView
    basis: list[str]


class LedgerEntryView(BaseModel):
    id: UUID
    occurred_at: datetime
    source_type: str
    source_id: UUID
    employee_id: UUID | None
    employee_name: str
    human_minutes_saved: float
    labor_cost_saved: float
    currency: str
    assumption_version: int | None
    created_at: datetime


class LedgerPage(BaseModel):
    items: list[LedgerEntryView]
    total: int
    limit: int
    offset: int


class MaterializeResult(BaseModel):
    business_unit_id: str
    from_at: datetime
    to_at: datetime
    created: int
    skipped_existing: int
    skipped_ineligible: int


class RebuildRequest(BaseModel):
    days: int = 30

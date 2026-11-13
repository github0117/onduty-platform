from datetime import date, datetime, time
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ShiftTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    start_local: time
    end_local: time


class ShiftTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    start_local: time | None = None
    end_local: time | None = None
    status: Literal["ACTIVE", "ARCHIVED"] | None = None
    version: int = Field(ge=1)


class ShiftTemplateView(BaseModel):
    id: UUID
    business_unit_id: str
    name: str
    start_local: time
    end_local: time
    status: str
    version: int
    created_by: str
    created_at: datetime
    updated_at: datetime
    cross_day: bool


class ShiftTemplateList(BaseModel):
    items: list[ShiftTemplateView]


class RosterEntryInput(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    shift_template_id: UUID
    shift_date: date


class RosterEntryView(BaseModel):
    id: UUID
    roster_id: UUID
    shift_template_id: UUID | None
    agent_id: str
    agent_display_name: str
    shift_date: date
    start_at: datetime
    end_at: datetime
    shift_name: str
    shift_version: int
    snapshot_json: dict[str, Any]


class RosterView(BaseModel):
    id: UUID
    business_unit_id: str
    week_start: date
    timezone: str
    status: str
    version: int
    cloned_from_roster_id: UUID | None
    created_by: str
    published_by: str | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
    entries: list[RosterEntryView]


class RosterList(BaseModel):
    items: list[RosterView]


class RosterCreate(BaseModel):
    week_start: date
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)


class RosterDraftUpdate(BaseModel):
    version: int = Field(ge=1)
    entries: list[RosterEntryInput] = Field(max_length=1000)


class SchedulingPolicyUpdate(BaseModel):
    enforce_published_schedule: bool


class SchedulingPolicyView(BaseModel):
    business_unit_id: str
    enforce_published_schedule: bool
    updated_by: str | None
    updated_at: datetime | None
    persisted: bool
    schedule_ready: bool
    coverage_gap: bool


class OnDutyAgentView(BaseModel):
    agent_id: str
    display_name: str
    online: bool
    auto_assign_enabled: bool
    schedule_enforced: bool
    on_shift: bool
    shift_start_at: datetime | None
    shift_end_at: datetime | None
    excluded_reasons: list[str]


class OnDutyList(BaseModel):
    business_unit_id: str
    now: datetime
    schedule_enforced: bool
    schedule_ready: bool
    coverage_gap: bool
    items: list[OnDutyAgentView]

"""Shift templates, weekly rosters and assignment-policy operations.

The service owns validation and state transitions. HTTP handlers commit and
write audit events; nothing here commits so a failed request leaves the
session clean for the dependency to roll back.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ticket_agent.customer_service.models import AgentPresence
from ticket_agent.scheduling.models import (
    AgentRoster,
    AgentRosterEntry,
    AgentSchedulingPolicy,
    AgentShiftTemplate,
)
from ticket_agent.scheduling.schemas import (
    OnDutyAgentView,
    OnDutyList,
    RosterDraftUpdate,
    RosterEntryInput,
    RosterEntryView,
    RosterList,
    RosterView,
    SchedulingPolicyUpdate,
    SchedulingPolicyView,
    ShiftTemplateCreate,
    ShiftTemplateList,
    ShiftTemplateUpdate,
    ShiftTemplateView,
)
from ticket_agent.shared.errors import ApiProblem

DEFAULT_TIMEZONE = "Asia/Shanghai"
WEEK_LENGTH_DAYS = 7
SHIFT_NOT_FOUND = ApiProblem(
    status_code=404,
    code="SHIFT_NOT_FOUND",
    title="Shift template not found",
    detail="班次不存在或不属于当前业务单元。",
)
ROSTER_NOT_FOUND = ApiProblem(
    status_code=404,
    code="ROSTER_NOT_FOUND",
    title="Roster not found",
    detail="班表不存在或不属于当前业务单元。",
)


@dataclass(frozen=True)
class ScheduleWindow:
    start_at: datetime
    end_at: datetime
    timezone: str


@dataclass(frozen=True)
class RosterMutation:
    view: RosterView
    changed: bool


def _problem(
    status_code: int,
    code: str,
    title: str,
    detail: str,
) -> ApiProblem:
    return ApiProblem(
        status_code=status_code,
        code=code,
        title=title,
        detail=detail,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _resolve_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise _problem(
            422,
            "INVALID_SHIFT_TIME",
            "Invalid roster timezone",
            f"时区“{name}”不可用，请使用 IANA 时区名称。",
        ) from exc


def _validate_week_start(value: date) -> date:
    if value.weekday() != 0:
        raise _problem(
            422,
            "INVALID_WEEK",
            "Invalid roster week",
            "week_start 必须是周一。",
        )
    return value


def parse_week_start(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise _problem(
            422,
            "INVALID_WEEK",
            "Invalid roster week",
            "week_start 必须是 YYYY-MM-DD 格式的周一。",
        ) from exc
    return _validate_week_start(parsed)


def _localize(shift_date: date, value: time, timezone: ZoneInfo) -> datetime:
    aware = datetime.combine(shift_date, value, tzinfo=timezone)
    if aware.utcoffset() != aware.replace(fold=1).utcoffset():
        raise _problem(
            422,
            "INVALID_SHIFT_TIME",
            "Invalid local shift time",
            f"本地时间 {shift_date.isoformat()} {value.isoformat()} 不存在或有歧义。",
        )
    roundtrip = aware.astimezone(UTC).astimezone(timezone)
    if (
        roundtrip.year,
        roundtrip.month,
        roundtrip.day,
        roundtrip.hour,
        roundtrip.minute,
    ) != (
        aware.year,
        aware.month,
        aware.day,
        aware.hour,
        aware.minute,
    ):
        raise _problem(
            422,
            "INVALID_SHIFT_TIME",
            "Invalid local shift time",
            f"本地时间 {shift_date.isoformat()} {value.isoformat()} 不存在或有歧义。",
        )
    return aware


def _shift_window(
    *,
    shift_date: date,
    start_local: time,
    end_local: time,
    timezone_name: str,
) -> tuple[datetime, datetime, bool]:
    if start_local == end_local:
        raise _problem(
            422,
            "INVALID_SHIFT_TIME",
            "Invalid shift time",
            "班次起止时间相同，请使用跨天时间表示夜班。",
        )
    timezone = _resolve_timezone(timezone_name)
    cross_day = end_local < start_local
    start_at = _localize(shift_date, start_local, timezone)
    end_date = shift_date + timedelta(days=1) if cross_day else shift_date
    end_at = _localize(end_date, end_local, timezone)
    return start_at, end_at, cross_day


def _cross_day(start_local: time, end_local: time) -> bool:
    return end_local < start_local


def _shift_view(template: AgentShiftTemplate) -> ShiftTemplateView:
    return ShiftTemplateView(
        id=template.id,
        business_unit_id=template.business_unit_id,
        name=template.name,
        start_local=template.start_local,
        end_local=template.end_local,
        status=template.status,
        version=template.version,
        created_by=template.created_by,
        created_at=template.created_at,
        updated_at=template.updated_at,
        cross_day=_cross_day(template.start_local, template.end_local),
    )


def _entry_view(entry: AgentRosterEntry) -> RosterEntryView:
    return RosterEntryView(
        id=entry.id,
        roster_id=entry.roster_id,
        shift_template_id=entry.shift_template_id,
        agent_id=entry.agent_id,
        agent_display_name=entry.agent_display_name,
        shift_date=entry.shift_date,
        start_at=entry.start_at,
        end_at=entry.end_at,
        shift_name=entry.shift_name,
        shift_version=entry.shift_version,
        snapshot_json=entry.snapshot_json,
    )


def _roster_view(roster: AgentRoster, entries: Sequence[AgentRosterEntry]) -> RosterView:
    ordered = sorted(
        entries,
        key=lambda entry: (entry.shift_date, entry.agent_id),
    )
    return RosterView(
        id=roster.id,
        business_unit_id=roster.business_unit_id,
        week_start=roster.week_start,
        timezone=roster.timezone,
        status=roster.status,
        version=roster.version,
        cloned_from_roster_id=roster.cloned_from_roster_id,
        created_by=roster.created_by,
        published_by=roster.published_by,
        published_at=roster.published_at,
        created_at=roster.created_at,
        updated_at=roster.updated_at,
        entries=[_entry_view(entry) for entry in ordered],
    )


def _entries_for(session: Session, roster_id: UUID) -> list[AgentRosterEntry]:
    return list(
        session.scalars(
            select(AgentRosterEntry).where(
                AgentRosterEntry.roster_id == roster_id
            )
        ).all()
    )


def _get_roster(
    session: Session,
    *,
    business_unit_id: str,
    roster_id: UUID,
    for_update: bool = False,
) -> AgentRoster:
    statement = select(AgentRoster).where(
        AgentRoster.id == roster_id,
        AgentRoster.business_unit_id == business_unit_id,
    )
    if for_update:
        statement = statement.with_for_update()
    roster = session.scalar(statement)
    if roster is None:
        raise ROSTER_NOT_FOUND
    return roster


def _get_shift(
    session: Session,
    *,
    business_unit_id: str,
    shift_id: UUID,
) -> AgentShiftTemplate:
    template = session.scalar(
        select(AgentShiftTemplate).where(
            AgentShiftTemplate.id == shift_id,
            AgentShiftTemplate.business_unit_id == business_unit_id,
        )
    )
    if template is None:
        raise SHIFT_NOT_FOUND
    return template


# ---------------------------------------------------------------------------
# Shift templates
# ---------------------------------------------------------------------------


def list_shifts(session: Session, *, business_unit_id: str) -> ShiftTemplateList:
    templates = session.scalars(
        select(AgentShiftTemplate)
        .where(AgentShiftTemplate.business_unit_id == business_unit_id)
        .order_by(AgentShiftTemplate.status, AgentShiftTemplate.name)
    ).all()
    return ShiftTemplateList(items=[_shift_view(item) for item in templates])


def create_shift(
    session: Session,
    *,
    business_unit_id: str,
    payload: ShiftTemplateCreate,
    actor_id: str,
) -> ShiftTemplateView:
    if payload.start_local == payload.end_local:
        raise _problem(
            422,
            "INVALID_SHIFT_TIME",
            "Invalid shift time",
            "班次起止时间相同，请使用跨天时间表示夜班。",
        )
    existing = session.scalar(
        select(AgentShiftTemplate).where(
            AgentShiftTemplate.business_unit_id == business_unit_id,
            AgentShiftTemplate.name == payload.name,
        )
    )
    if existing is not None:
        raise _shift_name_conflict(payload.name)
    template = AgentShiftTemplate(
        business_unit_id=business_unit_id,
        name=payload.name,
        start_local=payload.start_local,
        end_local=payload.end_local,
        status="ACTIVE",
        version=1,
        created_by=actor_id,
    )
    session.add(template)
    try:
        session.flush()
    except IntegrityError as exc:
        raise _shift_name_conflict(payload.name) from exc
    return _shift_view(template)


def update_shift(
    session: Session,
    *,
    business_unit_id: str,
    shift_id: UUID,
    payload: ShiftTemplateUpdate,
    actor_id: str,
) -> ShiftTemplateView:
    template = _get_shift(
        session,
        business_unit_id=business_unit_id,
        shift_id=shift_id,
    )
    if payload.version != template.version:
        raise _problem(
            409,
            "SHIFT_VERSION_CONFLICT",
            "Shift template version conflict",
            "班次已被他人修改，请刷新后重试。",
        )
    if payload.name is not None and payload.name != template.name:
        duplicate = session.scalar(
            select(AgentShiftTemplate).where(
                AgentShiftTemplate.business_unit_id == business_unit_id,
                AgentShiftTemplate.name == payload.name,
            )
        )
        if duplicate is not None:
            raise _shift_name_conflict(payload.name)
        template.name = payload.name
    if payload.start_local is not None:
        template.start_local = payload.start_local
    if payload.end_local is not None:
        template.end_local = payload.end_local
    if template.start_local == template.end_local:
        raise _problem(
            422,
            "INVALID_SHIFT_TIME",
            "Invalid shift time",
            "班次起止时间相同，请使用跨天时间表示夜班。",
        )
    if payload.status is not None:
        if payload.status == "ARCHIVED" and template.status != "ARCHIVED":
            referenced = session.scalar(
                select(AgentRosterEntry.id)
                .join(AgentRoster, AgentRoster.id == AgentRosterEntry.roster_id)
                .where(
                    AgentRoster.business_unit_id == business_unit_id,
                    AgentRoster.status == "DRAFT",
                    AgentRosterEntry.shift_template_id == template.id,
                )
                .limit(1)
            )
            if referenced is not None:
                raise _problem(
                    409,
                    "SHIFT_IN_USE",
                    "Shift template in use",
                    "该班次仍被草稿班表引用，请先调整草稿后再停用。",
                )
        template.status = payload.status
    template.version += 1
    template.updated_at = datetime.now(UTC)
    try:
        session.flush()
    except IntegrityError as exc:
        raise _shift_name_conflict(template.name) from exc
    return _shift_view(template)


def _shift_name_conflict(name: str) -> ApiProblem:
    return _problem(
        409,
        "SHIFT_NAME_CONFLICT",
        "Shift template name conflict",
        f"班次名称“{name}”已存在。",
    )


# ---------------------------------------------------------------------------
# Rosters
# ---------------------------------------------------------------------------


def list_rosters(
    session: Session,
    *,
    business_unit_id: str,
    week_start: date | None = None,
) -> RosterList:
    statement = select(AgentRoster).where(
        AgentRoster.business_unit_id == business_unit_id
    )
    if week_start is not None:
        statement = statement.where(AgentRoster.week_start == week_start)
    statement = statement.order_by(
        AgentRoster.week_start.desc(),
        AgentRoster.created_at.desc(),
    )
    rosters = list(session.scalars(statement).all())
    return RosterList(
        items=[
            _roster_view(roster, _entries_for(session, roster.id))
            for roster in rosters
        ]
    )


def get_roster(
    session: Session,
    *,
    business_unit_id: str,
    roster_id: UUID,
) -> RosterView:
    roster = _get_roster(
        session,
        business_unit_id=business_unit_id,
        roster_id=roster_id,
    )
    return _roster_view(roster, _entries_for(session, roster.id))


def get_or_create_draft(
    session: Session,
    *,
    business_unit_id: str,
    week_start: date,
    timezone_name: str,
    actor_id: str,
) -> RosterMutation:
    _validate_week_start(week_start)
    _resolve_timezone(timezone_name)
    roster = session.scalar(
        select(AgentRoster).where(
            AgentRoster.business_unit_id == business_unit_id,
            AgentRoster.week_start == week_start,
            AgentRoster.status == "DRAFT",
        )
    )
    if roster is not None:
        return RosterMutation(
            view=_roster_view(roster, _entries_for(session, roster.id)),
            changed=False,
        )
    published = session.scalar(
        select(AgentRoster).where(
            AgentRoster.business_unit_id == business_unit_id,
            AgentRoster.week_start == week_start,
            AgentRoster.status == "PUBLISHED",
        )
    )
    if published is not None:
        raise _problem(
            409,
            "INVALID_ROSTER_STATE",
            "Roster already published",
            "该周已有发布版本，请从发布版本或历史版本克隆修订。",
        )
    roster = AgentRoster(
        business_unit_id=business_unit_id,
        week_start=week_start,
        timezone=timezone_name,
        status="DRAFT",
        version=1,
        created_by=actor_id,
    )
    session.add(roster)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(AgentRoster).where(
                AgentRoster.business_unit_id == business_unit_id,
                AgentRoster.week_start == week_start,
                AgentRoster.status == "DRAFT",
            )
        )
        if existing is None:
            raise
        return RosterMutation(
            view=_roster_view(existing, _entries_for(session, existing.id)),
            changed=False,
        )
    return RosterMutation(
        view=_roster_view(roster, []),
        changed=True,
    )


def save_draft(
    session: Session,
    *,
    business_unit_id: str,
    roster_id: UUID,
    payload: RosterDraftUpdate,
    actor_id: str,
) -> RosterMutation:
    del actor_id
    roster = _get_roster(
        session,
        business_unit_id=business_unit_id,
        roster_id=roster_id,
    )
    if roster.status != "DRAFT":
        raise _problem(
            409,
            "INVALID_ROSTER_STATE",
            "Roster is not a draft",
            "只有草稿班表可以保存条目。",
        )
    existing_entries = _entries_for(session, roster.id)
    if _same_entries(existing_entries, payload.entries):
        return RosterMutation(
            view=_roster_view(roster, existing_entries),
            changed=False,
        )
    if payload.version != roster.version:
        raise _problem(
            409,
            "ROSTER_VERSION_CONFLICT",
            "Roster version conflict",
            "草稿已被他人修改，请刷新后重试。",
        )
    prepared = _prepare_entries(
        session,
        business_unit_id=business_unit_id,
        roster=roster,
        inputs=payload.entries,
    )
    session.execute(
        delete(AgentRosterEntry).where(AgentRosterEntry.roster_id == roster.id)
    )
    session.flush()
    for entry in prepared:
        entry.roster_id = roster.id
        session.add(entry)
    roster.version += 1
    roster.updated_at = datetime.now(UTC)
    session.flush()
    return RosterMutation(
        view=_roster_view(roster, prepared),
        changed=True,
    )


def _same_entries(
    existing: Sequence[AgentRosterEntry],
    requested: Sequence[RosterEntryInput],
) -> bool:
    if len(existing) != len(requested):
        return False
    current = {
        (entry.agent_id, entry.shift_template_id, entry.shift_date)
        for entry in existing
    }
    proposed = {
        (entry.agent_id, entry.shift_template_id, entry.shift_date)
        for entry in requested
    }
    return current == proposed


def _prepare_entries(
    session: Session,
    *,
    business_unit_id: str,
    roster: AgentRoster,
    inputs: Iterable[RosterEntryInput],
) -> list[AgentRosterEntry]:
    items = list(inputs)
    week_end = roster.week_start + timedelta(days=WEEK_LENGTH_DAYS - 1)
    shift_ids = {item.shift_template_id for item in items}
    templates: dict[UUID, AgentShiftTemplate] = {}
    if shift_ids:
        rows = session.scalars(
            select(AgentShiftTemplate).where(
                AgentShiftTemplate.id.in_(shift_ids),
                AgentShiftTemplate.business_unit_id == business_unit_id,
            )
        ).all()
        templates = {row.id: row for row in rows}
    agent_ids = {item.agent_id for item in items}
    presence_map: dict[str, AgentPresence] = {}
    if agent_ids:
        presence_rows = session.scalars(
            select(AgentPresence).where(
                AgentPresence.agent_id.in_(agent_ids),
                AgentPresence.business_unit_id == business_unit_id,
            )
        ).all()
        presence_map = {row.agent_id: row for row in presence_rows}

    seen: set[tuple[str, date]] = set()
    prepared: list[AgentRosterEntry] = []
    for index, item in enumerate(items):
        if item.shift_date < roster.week_start or item.shift_date > week_end:
            raise _invalid_entry(
                index,
                "班表日期必须位于所选周内。",
            )
        key = (item.agent_id, item.shift_date)
        if key in seen:
            raise _invalid_entry(
                index,
                f"坐席 {item.agent_id} 在 {item.shift_date.isoformat()} 有重复班次。",
            )
        seen.add(key)
        template = templates.get(item.shift_template_id)
        if template is None:
            raise _invalid_entry(index, "班次模板不存在或不属于当前业务单元。")
        if template.status != "ACTIVE":
            raise _invalid_entry(
                index,
                f"班次“{template.name}”已停用，不能排班。",
            )
        presence = presence_map.get(item.agent_id)
        if presence is None:
            raise _problem(
                422,
                "AGENT_NOT_FOUND",
                "Agent not found",
                f"坐席 {item.agent_id} 不存在于当前业务单元的坐席目录。",
            )
        start_at, end_at, cross_day = _shift_window(
            shift_date=item.shift_date,
            start_local=template.start_local,
            end_local=template.end_local,
            timezone_name=roster.timezone,
        )
        prepared.append(
            AgentRosterEntry(
                roster_id=roster.id,
                shift_template_id=template.id,
                agent_id=item.agent_id,
                agent_display_name=presence.display_name,
                shift_date=item.shift_date,
                start_at=start_at,
                end_at=end_at,
                shift_name=template.name,
                shift_version=template.version,
                snapshot_json={
                    "shift_name": template.name,
                    "shift_version": template.version,
                    "start_local": template.start_local.isoformat(
                        timespec="minutes"
                    ),
                    "end_local": template.end_local.isoformat(
                        timespec="minutes"
                    ),
                    "timezone": roster.timezone,
                    "cross_day": cross_day,
                    "shift_date": item.shift_date.isoformat(),
                },
            )
        )
    return prepared


def _invalid_entry(index: int, detail: str) -> ApiProblem:
    return ApiProblem(
        status_code=422,
        code="INVALID_ROSTER_ENTRY",
        title="Invalid roster entry",
        detail=detail,
        context={"index": index},
    )


def publish(
    session: Session,
    *,
    business_unit_id: str,
    roster_id: UUID,
    actor_id: str,
) -> RosterMutation:
    roster = _get_roster(
        session,
        business_unit_id=business_unit_id,
        roster_id=roster_id,
        for_update=True,
    )
    if roster.status == "PUBLISHED":
        return RosterMutation(
            view=_roster_view(roster, _entries_for(session, roster.id)),
            changed=False,
        )
    if roster.status == "ARCHIVED":
        raise _problem(
            409,
            "INVALID_ROSTER_STATE",
            "Roster is archived",
            "已归档的班表不能再次发布，请克隆修订后再发布。",
        )
    entries = _entries_for(session, roster.id)
    if not entries:
        raise _problem(
            422,
            "EMPTY_ROSTER",
            "Cannot publish an empty roster",
            "班表没有任何条目，无法发布。",
        )
    previous = session.scalars(
        select(AgentRoster).where(
            AgentRoster.business_unit_id == business_unit_id,
            AgentRoster.week_start == roster.week_start,
            AgentRoster.status == "PUBLISHED",
            AgentRoster.id != roster.id,
        )
    ).all()
    for item in previous:
        item.status = "ARCHIVED"
        item.updated_at = datetime.now(UTC)
    if previous:
        # Flush the archive before publishing: the partial unique index allows
        # only one PUBLISHED row per unit/week, so both statements cannot be
        # part of the same batch.
        session.flush()
    now = datetime.now(UTC)
    roster.status = "PUBLISHED"
    roster.published_by = actor_id
    roster.published_at = now
    roster.updated_at = now
    try:
        session.flush()
    except IntegrityError as exc:
        raise _problem(
            409,
            "INVALID_ROSTER_STATE",
            "Roster publish conflict",
            "该周已有其他发布版本，请刷新后重试。",
        ) from exc
    return RosterMutation(
        view=_roster_view(roster, entries),
        changed=True,
    )


def clone_roster(
    session: Session,
    *,
    business_unit_id: str,
    source_roster_id: UUID,
    actor_id: str,
) -> RosterMutation:
    source = _get_roster(
        session,
        business_unit_id=business_unit_id,
        roster_id=source_roster_id,
    )
    if source.status == "DRAFT":
        raise _problem(
            409,
            "INVALID_ROSTER_STATE",
            "Cannot clone a draft",
            "草稿不能作为克隆源，请从发布版本或归档版本克隆。",
        )
    draft = session.scalar(
        select(AgentRoster).where(
            AgentRoster.business_unit_id == business_unit_id,
            AgentRoster.week_start == source.week_start,
            AgentRoster.status == "DRAFT",
        )
    )
    if draft is not None:
        raise _problem(
            409,
            "ROSTER_DRAFT_EXISTS",
            "Roster draft already exists",
            "该周已有草稿，请直接编辑或先处理现有草稿。",
        )
    clone = AgentRoster(
        business_unit_id=business_unit_id,
        week_start=source.week_start,
        timezone=source.timezone,
        status="DRAFT",
        version=1,
        cloned_from_roster_id=source.id,
        created_by=actor_id,
    )
    session.add(clone)
    try:
        session.flush()
    except IntegrityError as exc:
        raise _problem(
            409,
            "ROSTER_DRAFT_EXISTS",
            "Roster draft already exists",
            "该周已有草稿，请直接编辑或先处理现有草稿。",
        ) from exc
    entries = [
        AgentRosterEntry(
            roster_id=clone.id,
            shift_template_id=entry.shift_template_id,
            agent_id=entry.agent_id,
            agent_display_name=entry.agent_display_name,
            shift_date=entry.shift_date,
            start_at=entry.start_at,
            end_at=entry.end_at,
            shift_name=entry.shift_name,
            shift_version=entry.shift_version,
            snapshot_json=dict(entry.snapshot_json),
        )
        for entry in _entries_for(session, source.id)
    ]
    for entry in entries:
        session.add(entry)
    session.flush()
    return RosterMutation(
        view=_roster_view(clone, entries),
        changed=True,
    )


# ---------------------------------------------------------------------------
# Policy and on-duty state
# ---------------------------------------------------------------------------


def _current_week_start(now: datetime) -> date:
    local = now.astimezone(ZoneInfo(DEFAULT_TIMEZONE)).date()
    return local - timedelta(days=local.weekday())


def _schedule_ready(
    session: Session,
    *,
    business_unit_id: str,
    now: datetime,
) -> bool:
    published = session.scalar(
        select(AgentRoster.id)
        .where(
            AgentRoster.business_unit_id == business_unit_id,
            AgentRoster.status == "PUBLISHED",
            AgentRoster.week_start == _current_week_start(now),
        )
        .limit(1)
    )
    return published is not None


def _policy_row(
    session: Session,
    *,
    business_unit_id: str,
) -> AgentSchedulingPolicy | None:
    return session.get(AgentSchedulingPolicy, business_unit_id)


def _policy_view(
    session: Session,
    *,
    business_unit_id: str,
    now: datetime,
) -> SchedulingPolicyView:
    row = _policy_row(session, business_unit_id=business_unit_id)
    ready = _schedule_ready(
        session,
        business_unit_id=business_unit_id,
        now=now,
    )
    return SchedulingPolicyView(
        business_unit_id=business_unit_id,
        enforce_published_schedule=(
            row.enforce_published_schedule if row is not None else False
        ),
        updated_by=row.updated_by if row is not None else None,
        updated_at=row.updated_at if row is not None else None,
        persisted=row is not None,
        schedule_ready=ready,
        coverage_gap=not ready,
    )


def get_policy(
    session: Session,
    *,
    business_unit_id: str,
    now: datetime | None = None,
) -> SchedulingPolicyView:
    return _policy_view(
        session,
        business_unit_id=business_unit_id,
        now=now or datetime.now(UTC),
    )


def update_policy(
    session: Session,
    *,
    business_unit_id: str,
    payload: SchedulingPolicyUpdate,
    actor_id: str,
    now: datetime | None = None,
) -> SchedulingPolicyView:
    current = now or datetime.now(UTC)
    if payload.enforce_published_schedule and not _schedule_ready(
        session,
        business_unit_id=business_unit_id,
        now=current,
    ):
        raise _problem(
            422,
            "SCHEDULE_NOT_READY",
            "Published schedule not ready",
            "开启按班表约束前，必须先发布覆盖当前周的班表。",
        )
    row = _policy_row(session, business_unit_id=business_unit_id)
    if row is None:
        row = AgentSchedulingPolicy(
            business_unit_id=business_unit_id,
            enforce_published_schedule=payload.enforce_published_schedule,
            updated_by=actor_id,
        )
        session.add(row)
    else:
        row.enforce_published_schedule = payload.enforce_published_schedule
        row.updated_by = actor_id
        row.updated_at = current
    session.flush()
    return _policy_view(
        session,
        business_unit_id=business_unit_id,
        now=current,
    )


def enforced_business_units(
    session: Session,
    *,
    business_unit_ids: Sequence[str],
) -> set[str]:
    if not business_unit_ids:
        return set()
    rows = session.scalars(
        select(AgentSchedulingPolicy.business_unit_id).where(
            AgentSchedulingPolicy.business_unit_id.in_(business_unit_ids),
            AgentSchedulingPolicy.enforce_published_schedule.is_(True),
        )
    ).all()
    return set(rows)


def shift_windows(
    session: Session,
    *,
    business_unit_id: str,
    agent_ids: Sequence[str],
    now: datetime,
) -> dict[str, ScheduleWindow]:
    """Return the current shift window for each agent that is on duty."""
    if not agent_ids:
        return {}
    rows = cast(
        Sequence[tuple[str, datetime, datetime, object]],
        session.execute(
            select(
                AgentRosterEntry.agent_id,
                AgentRosterEntry.start_at,
                AgentRosterEntry.end_at,
                AgentRosterEntry.snapshot_json,
            )
            .join(AgentRoster, AgentRoster.id == AgentRosterEntry.roster_id)
            .where(
                AgentRoster.business_unit_id == business_unit_id,
                AgentRoster.status == "PUBLISHED",
                AgentRosterEntry.agent_id.in_(agent_ids),
            )
            .order_by(AgentRosterEntry.start_at.desc())
        ).all(),
    )
    windows: dict[str, ScheduleWindow] = {}
    for agent_id, start_at, end_at, snapshot in rows:
        if agent_id in windows:
            continue
        if not (_as_utc(start_at) <= now < _as_utc(end_at)):
            continue
        timezone_name = DEFAULT_TIMEZONE
        if isinstance(snapshot, dict):
            candidate = snapshot.get("timezone")
            if isinstance(candidate, str):
                timezone_name = candidate
        windows[agent_id] = ScheduleWindow(
            start_at=_as_utc(start_at),
            end_at=_as_utc(end_at),
            timezone=timezone_name,
        )
    return windows


def on_duty(
    session: Session,
    *,
    business_unit_id: str,
    now: datetime | None = None,
) -> OnDutyList:
    current = now or datetime.now(UTC)
    policy = _policy_view(
        session,
        business_unit_id=business_unit_id,
        now=current,
    )
    presences = list(
        session.scalars(
            select(AgentPresence)
            .where(AgentPresence.business_unit_id == business_unit_id)
            .order_by(AgentPresence.agent_id)
        ).all()
    )
    windows = shift_windows(
        session,
        business_unit_id=business_unit_id,
        agent_ids=[item.agent_id for item in presences],
        now=current,
    )
    cutoff = current - timedelta(seconds=60)
    items: list[OnDutyAgentView] = []
    for presence in presences:
        window = windows.get(presence.agent_id)
        online = (
            presence.status == "ONLINE"
            and _as_utc(presence.last_seen_at) >= cutoff
        )
        reasons: list[str] = []
        if not online:
            reasons.append("坐席不在线")
        if not presence.auto_assign_enabled:
            reasons.append("已关闭自动分配")
        if policy.enforce_published_schedule and window is None:
            reasons.append("未在已发布班表当班")
        items.append(
            OnDutyAgentView(
                agent_id=presence.agent_id,
                display_name=presence.display_name,
                online=online,
                auto_assign_enabled=presence.auto_assign_enabled,
                schedule_enforced=policy.enforce_published_schedule,
                on_shift=window is not None,
                shift_start_at=window.start_at if window else None,
                shift_end_at=window.end_at if window else None,
                excluded_reasons=reasons,
            )
        )
    return OnDutyList(
        business_unit_id=business_unit_id,
        now=current,
        schedule_enforced=policy.enforce_published_schedule,
        schedule_ready=policy.schedule_ready,
        coverage_gap=policy.coverage_gap,
        items=items,
    )


def format_shift_window(window: ScheduleWindow) -> str:
    timezone = _resolve_timezone(window.timezone)
    start = window.start_at.astimezone(timezone).strftime("%m-%d %H:%M")
    end = window.end_at.astimezone(timezone).strftime("%m-%d %H:%M")
    return f"{start}–{end}"

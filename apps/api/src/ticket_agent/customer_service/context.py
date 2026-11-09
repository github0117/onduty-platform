"""Assemble what one turn actually sees, and read back what it remembered.

Before M1 each consumer derived its own view of the conversation: the turn
worker joined the last eight messages into a string, the suggestion service did
the same again, and memory was written but never read. This module is the single
place that answers "what is the context of this turn?" so the answer can be
snapshotted onto the turn and inspected later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ticket_agent.customer_service.models import (
    ConversationHandoff,
    ConversationMemory,
    ConversationTurn,
    CustomerMessage,
)
from ticket_agent.digital_employees.models import DigitalEmployee

MEMORY_SCHEMA_VERSION = 2
DEFAULT_HISTORY_BUDGET_CHARS = 4000
DEFAULT_HISTORY_MAX_MESSAGES = 20

# v1 memory stored a flat map of scalar slots. These are the keys that were
# treated as established facts.
_LEGACY_FACT_KEYS = (
    "repository",
    "order_id",
    "product_id",
    "sku",
    "tracking_number",
    "address",
)


@dataclass(frozen=True)
class MemorySnapshot:
    schema_version: int
    summary: str
    facts: dict[str, dict[str, object]]
    open_actions: list[dict[str, object]]
    commitments: list[dict[str, object]]
    pending_questions: list[str]
    version: int
    last_turn_sequence: int
    upgraded_from_v1: bool

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "version": self.version,
            "last_turn_sequence": self.last_turn_sequence,
            "summary": self.summary,
            "fact_count": len(self.facts),
            "open_action_count": len(self.open_actions),
            "commitment_count": len(self.commitments),
            "pending_question_count": len(self.pending_questions),
            "upgraded_from_v1": self.upgraded_from_v1,
        }

    def prompt_lines(self) -> list[str]:
        """Render memory as the lines a prompt can consume, in a fixed order."""
        lines: list[str] = []
        if self.summary:
            lines.append(f"会话摘要：{self.summary}")
        for key, fact in self.facts.items():
            status = fact.get("status", "confirmed")
            lines.append(f"已确认事实（{status}）：{key} = {fact.get('value')}")
        for action in self.open_actions:
            lines.append(f"未完成事项：{action.get('summary')}")
        for commitment in self.commitments:
            lines.append(f"已承诺：{commitment.get('text')}")
        for question in self.pending_questions:
            lines.append(f"待确认问题：{question}")
        return lines


@dataclass(frozen=True)
class HandoffSnapshot:
    id: UUID
    kind: str
    reason_code: str
    from_employee_id: UUID | None
    to_employee_id: UUID | None
    from_turn_id: UUID | None
    summary: dict[str, object]

    def as_payload(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "kind": self.kind,
            "reason_code": self.reason_code,
            "from_employee_id": (
                str(self.from_employee_id) if self.from_employee_id else None
            ),
            "to_employee_id": (
                str(self.to_employee_id) if self.to_employee_id else None
            ),
            "from_turn_id": (
                str(self.from_turn_id) if self.from_turn_id else None
            ),
        }


@dataclass(frozen=True)
class AssembledContext:
    query: str
    history: list[str]
    memory: MemorySnapshot | None
    handoff: HandoffSnapshot | None
    used_message_ids: list[UUID]
    payload: dict[str, object]

    def prompt_lines(self) -> list[str]:
        """Memory and handoff lines, in assembly order."""
        lines: list[str] = []
        if self.memory is not None:
            lines.extend(self.memory.prompt_lines())
        if self.handoff is not None:
            lines.extend(_handoff_prompt_lines(self.handoff.summary))
        return lines

    def window_text(self) -> str:
        """The recent message window in the legacy ``买家：…`` shape.

        Downstream helpers (buyer-history extraction, repository detection)
        already parse this shape, so the assembler keeps producing it while the
        budget and the employee labels become explicit.
        """
        return "\n".join([*self.history, f"买家：{self.query}"])


def load_memory(
    session: Session,
    conversation_id: UUID,
    *,
    persist_upgrade: bool = True,
) -> MemorySnapshot | None:
    """Read memory, upgrading a v1 row to the v2 shape on the way out.

    The upgrade is written back so a conversation only migrates once. The
    caller is already inside a write transaction when a turn runs, so the extra
    update costs nothing extra.
    """
    memory = session.get(ConversationMemory, conversation_id)
    if memory is None:
        return None
    slots = memory.slots_json or {}
    stored_version = int(memory.schema_version or 1)
    if stored_version >= MEMORY_SCHEMA_VERSION and "facts" in slots:
        return MemorySnapshot(
            schema_version=MEMORY_SCHEMA_VERSION,
            summary=memory.summary,
            facts=_dict_of_dicts(slots.get("facts")),
            open_actions=_list_of_dicts(slots.get("open_actions")),
            commitments=_list_of_dicts(slots.get("commitments")),
            pending_questions=[
                str(item) for item in _as_list(slots.get("pending_questions"))
            ],
            version=memory.version,
            last_turn_sequence=memory.last_turn_sequence,
            upgraded_from_v1=False,
        )

    facts: dict[str, dict[str, object]] = {}
    for key in _LEGACY_FACT_KEYS:
        value = slots.get(key)
        if value in (None, ""):
            continue
        facts[key] = {
            "value": value,
            "status": "confirmed",
            "source_turn_id": None,
            "updated_at": _isoformat(memory.updated_at),
        }
    snapshot = MemorySnapshot(
        schema_version=MEMORY_SCHEMA_VERSION,
        summary=memory.summary,
        facts=facts,
        open_actions=[],
        commitments=[],
        pending_questions=[],
        version=memory.version,
        last_turn_sequence=memory.last_turn_sequence,
        upgraded_from_v1=True,
    )
    if persist_upgrade:
        memory.schema_version = MEMORY_SCHEMA_VERSION
        memory.slots_json = _slots_payload(snapshot)
        memory.version = memory.version + 1
        session.flush()
    return snapshot


def latest_handoff(
    session: Session,
    conversation_id: UUID,
) -> HandoffSnapshot | None:
    handoff = session.scalar(
        select(ConversationHandoff)
        .where(ConversationHandoff.conversation_id == conversation_id)
        .order_by(ConversationHandoff.created_at.desc())
        .limit(1)
    )
    if handoff is None:
        return None
    return HandoffSnapshot(
        id=handoff.id,
        kind=handoff.kind,
        reason_code=handoff.reason_code,
        from_employee_id=handoff.from_employee_id,
        to_employee_id=handoff.to_employee_id,
        from_turn_id=handoff.from_turn_id,
        summary=dict(handoff.summary_json or {}),
    )


def assemble_context(
    session: Session,
    *,
    conversation_id: UUID,
    current_message: CustomerMessage,
    budget_chars: int = DEFAULT_HISTORY_BUDGET_CHARS,
    max_messages: int = DEFAULT_HISTORY_MAX_MESSAGES,
    persist_memory_upgrade: bool = True,
) -> AssembledContext:
    """Build the fixed-order context of one turn.

    Order: memory (summary, facts, open actions, commitments, open questions)
    -> latest handoff summary -> recent message window -> current message.
    Retrieval results are appended by the suggestion graph, not here.
    """
    memory = load_memory(
        session,
        conversation_id,
        persist_upgrade=persist_memory_upgrade,
    )
    handoff = latest_handoff(session, conversation_id)
    # Only what was said before this message. A queued turn may run after the
    # buyer has already sent the next message; that later message must not
    # leak into this turn's context.
    previous = list(
        session.scalars(
            select(CustomerMessage)
            .where(
                CustomerMessage.conversation_id == conversation_id,
                CustomerMessage.sequence < current_message.sequence,
            )
            .order_by(CustomerMessage.sequence.desc())
            .limit(max_messages)
        ).all()
    )
    labels = _employee_labels(session, [item.turn_id for item in previous])
    selected: list[CustomerMessage] = []
    used_chars = 0
    truncated = len(previous) >= max_messages
    for message in previous:  # newest first, so the budget keeps recent turns
        line = _message_line(message, labels)
        if selected and used_chars + len(line) > budget_chars:
            truncated = True
            break
        selected.append(message)
        used_chars += len(line)
    selected.reverse()

    history = [_message_line(message, labels) for message in selected]
    payload: dict[str, object] = {
        "schema_version": MEMORY_SCHEMA_VERSION,
        "budget_chars": budget_chars,
        "max_messages": max_messages,
        "history_message_count": len(selected),
        "history_sequences": [message.sequence for message in selected],
        "history_turn_ids": [
            str(message.turn_id) for message in selected if message.turn_id
        ],
        "truncated": truncated,
        "memory": memory.as_payload() if memory is not None else None,
        "handoff": handoff.as_payload() if handoff is not None else None,
    }
    return AssembledContext(
        query=current_message.content.strip(),
        history=history,
        memory=memory,
        handoff=handoff,
        used_message_ids=[message.id for message in selected],
        payload=payload,
    )


def record_memory_turn(
    session: Session,
    *,
    conversation_id: UUID,
    turn_sequence: int,
    summary: str,
    facts: dict[str, dict[str, object]] | None = None,
    open_actions: list[dict[str, object]] | None = None,
    commitments: list[dict[str, object]] | None = None,
    pending_questions: list[str] | None = None,
) -> MemorySnapshot:
    """Append one answered turn to memory in the v2 shape.

    ``summary`` is the whole rolling summary; ``facts`` are structured values
    the turn confirmed (order id, address, ...). Each fact keeps the turn that
    established it so a later turn can explain where a value came from.
    ``open_actions``, ``commitments`` and ``pending_questions`` replace the
    stored slots when provided; ``None`` keeps the previous value.
    """
    memory = session.get(ConversationMemory, conversation_id)
    if memory is None:
        memory = ConversationMemory(
            conversation_id=conversation_id,
            summary="",
            slots_json=_slots_payload(
                MemorySnapshot(
                    schema_version=MEMORY_SCHEMA_VERSION,
                    summary="",
                    facts={},
                    open_actions=[],
                    commitments=[],
                    pending_questions=[],
                    version=0,
                    last_turn_sequence=0,
                    upgraded_from_v1=False,
                )
            ),
            last_turn_sequence=0,
            schema_version=MEMORY_SCHEMA_VERSION,
        )
        session.add(memory)
        session.flush()

    snapshot = load_memory(session, conversation_id, persist_upgrade=True)
    assert snapshot is not None  # created just above
    merged_facts = dict(snapshot.facts)
    for key, fact in (facts or {}).items():
        merged_facts[key] = fact
    next_snapshot = MemorySnapshot(
        schema_version=MEMORY_SCHEMA_VERSION,
        summary=summary,
        facts=merged_facts,
        open_actions=(
            snapshot.open_actions
            if open_actions is None
            else open_actions
        ),
        commitments=(
            snapshot.commitments
            if commitments is None
            else commitments
        ),
        pending_questions=(
            snapshot.pending_questions
            if pending_questions is None
            else pending_questions
        ),
        version=snapshot.version + 1,
        last_turn_sequence=turn_sequence,
        upgraded_from_v1=False,
    )
    memory.summary = next_snapshot.summary
    memory.slots_json = _slots_payload(next_snapshot)
    memory.last_turn_sequence = turn_sequence
    memory.summarized_through_sequence = turn_sequence
    memory.schema_version = MEMORY_SCHEMA_VERSION
    memory.version = next_snapshot.version
    session.flush()
    return next_snapshot


MAX_OPEN_ACTIONS = 5
MAX_COMMITMENTS = 5
MAX_PENDING_QUESTIONS = 3

_MAX_SLOT_TEXT = 200
_MAX_QUESTION_TEXT = 120

_COMMITMENT_MARKERS = (
    "已为您",
    "已提交",
    "已安排",
    "已反馈",
    "已记录",
    "已转",
    "预计",
    "将在",
    "会在",
    "稍后",
    "马上",
    "尽快",
    "工作日",
    "小时内",
    "为您跟进",
    "帮您跟进",
)
_ACTION_MARKERS = (
    "转人工",
    "等待人工",
    "等待审批",
    "待审批",
    "等待审核",
    "待审核",
    "需人工",
    "需要人工",
    "处理中",
    "正在处理",
    "待确认",
    "等待您",
    "等待回复",
    "待补充",
    "需补充",
    "等待物流",
    "等待供应商",
    "跟进中",
)
_SENTENCE_SPLIT_RE = re.compile(r"[。！!\n；;]+")
_QUESTION_RE = re.compile(r"([^\n？?。！!]{2,120})[？?]")
_SLOT_KEY_RE = re.compile(r"[^\w]+")


@dataclass(frozen=True)
class DerivedSlots:
    open_actions: list[dict[str, object]]
    commitments: list[dict[str, object]]
    pending_questions: list[str]


def derive_memory_slots(
    *,
    previous: MemorySnapshot | None,
    assistant_content: str,
    turn_sequence: int,
    source_turn_id: str | None,
    updated_at: str,
    ticket_status: str | None = None,
) -> DerivedSlots:
    """Derive the structured memory slots from the answer of one turn.

    The rules are deterministic on purpose: no model call, no hidden state.
    - ``commitments`` keep the newest entries and survive across turns.
    - ``open_actions`` are dropped once the ticket reaches a terminal status.
    - ``pending_questions`` only reflect the latest answer, because a new
      buyer message means the previous questions were answered or replaced.
    """
    completed = str(ticket_status or "").upper() in {"RESOLVED", "CLOSED"}
    previous_actions = previous.open_actions if previous is not None else []
    previous_commitments = previous.commitments if previous is not None else []

    commitments = _merge_slots(
        previous_commitments,
        _collect_entries(
            assistant_content,
            markers=_COMMITMENT_MARKERS,
            field="text",
            turn_sequence=turn_sequence,
            source_turn_id=source_turn_id,
            updated_at=updated_at,
        ),
        key="text",
        limit=MAX_COMMITMENTS,
    )
    open_actions = (
        []
        if completed
        else _merge_slots(
            previous_actions,
            _collect_entries(
                assistant_content,
                markers=_ACTION_MARKERS,
                field="summary",
                turn_sequence=turn_sequence,
                source_turn_id=source_turn_id,
                updated_at=updated_at,
            ),
            key="summary",
            limit=MAX_OPEN_ACTIONS,
        )
    )
    pending_questions = [] if completed else _collect_questions(
        assistant_content
    )
    return DerivedSlots(
        open_actions=open_actions,
        commitments=commitments,
        pending_questions=pending_questions,
    )


def _collect_entries(
    content: str,
    *,
    markers: tuple[str, ...],
    field: str,
    turn_sequence: int,
    source_turn_id: str | None,
    updated_at: str,
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for sentence in _SENTENCE_SPLIT_RE.split(content):
        text = sentence.strip()
        if not text or "？" in text or "?" in text:
            continue
        if not any(marker in text for marker in markers):
            continue
        entry: dict[str, object] = {
            field: text[:_MAX_SLOT_TEXT],
            "status": "open",
            "turn_sequence": turn_sequence,
            "source_turn_id": source_turn_id,
            "updated_at": updated_at,
        }
        if field == "summary":
            entry["owner"] = "employee"
        entries.append(entry)
    return entries


def _collect_questions(content: str) -> list[str]:
    questions: list[str] = []
    seen: set[str] = set()
    for match in _QUESTION_RE.finditer(content):
        text = match.group(1).strip()
        if not text:
            continue
        key = _slot_key(text)
        if key in seen:
            continue
        seen.add(key)
        questions.append(text[:_MAX_QUESTION_TEXT])
        if len(questions) >= MAX_PENDING_QUESTIONS:
            break
    return questions


def _merge_slots(
    previous: list[dict[str, object]],
    entries: list[dict[str, object]],
    *,
    key: str,
    limit: int,
) -> list[dict[str, object]]:
    merged = [dict(item) for item in previous]
    seen = {_slot_key(str(item.get(key, ""))) for item in merged}
    for entry in entries:
        marker = _slot_key(str(entry[key]))
        if not marker or marker in seen:
            continue
        merged.append(entry)
        seen.add(marker)
    return merged[-limit:]


def _slot_key(text: str) -> str:
    return _SLOT_KEY_RE.sub("", text).casefold()


def _employee_labels(
    session: Session,
    turn_ids: list[UUID | None],
) -> dict[UUID, str]:
    wanted = [turn_id for turn_id in turn_ids if turn_id is not None]
    if not wanted:
        return {}
    turn_employees = {
        turn_id: employee_id
        for turn_id, employee_id in session.execute(
            select(ConversationTurn.id, ConversationTurn.employee_id).where(
                ConversationTurn.id.in_(wanted)
            )
        ).all()
    }
    employee_ids = {
        employee_id
        for employee_id in turn_employees.values()
        if employee_id is not None
    }
    names: dict[UUID, str] = {}
    if employee_ids:
        for employee_id, name in session.execute(
            select(DigitalEmployee.id, DigitalEmployee.name).where(
                DigitalEmployee.id.in_(employee_ids)
            )
        ).all():
            names[employee_id] = name
    labels: dict[UUID, str] = {}
    for label_turn_id, label_employee_id in turn_employees.items():
        label = (
            names.get(label_employee_id)
            if label_employee_id is not None
            else None
        )
        labels[label_turn_id] = label or "数字员工"
    return labels


def _message_line(
    message: CustomerMessage,
    labels: dict[UUID, str],
) -> str:
    if message.role == "BUYER":
        speaker = "买家"
    elif message.turn_id is not None:
        speaker = f"客服（{labels.get(message.turn_id, '数字员工')}）"
    elif (message.created_by or "") not in {"", "digital_employee"}:
        # A manual reply has no turn: a person wrote it through the
        # workbench. Labeling it as the digital employee would make the next
        # turn believe it had said something it never said.
        speaker = "客服（人工）"
    else:
        speaker = "客服（数字员工）"
    text = message.content.strip()
    if len(text) > 600:
        text = f"{text[:600]}…"
    return f"{speaker}：{text}"


def _handoff_prompt_lines(summary: dict[str, object]) -> list[str]:
    lines: list[str] = []
    for fact in _list_of_dicts(summary.get("confirmed_facts")):
        lines.append(f"交接确认事实：{fact.get('key')} = {fact.get('value')}")
    for action in _list_of_dicts(summary.get("open_actions")):
        lines.append(f"交接未完成事项：{action.get('summary')}")
    for commitment in _list_of_dicts(summary.get("commitments")):
        lines.append(f"交接已承诺：{commitment.get('text')}")
    last_answer = summary.get("last_answer")
    if isinstance(last_answer, dict) and last_answer.get("text"):
        lines.append(f"交接上一轮回答：{last_answer['text']}")
    for question in _as_list(summary.get("pending_questions")):
        lines.append(f"交接待确认问题：{question}")
    for item in _as_list(summary.get("unverified")):
        lines.append(f"交接未核验内容：{item}")
    return lines


def _slots_payload(snapshot: MemorySnapshot) -> dict[str, object]:
    return {
        "schema_version": MEMORY_SCHEMA_VERSION,
        "facts": snapshot.facts,
        "open_actions": snapshot.open_actions,
        "commitments": snapshot.commitments,
        "pending_questions": snapshot.pending_questions,
    }


def _dict_of_dicts(value: object) -> dict[str, dict[str, object]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, dict[str, object]] = {}
    for key, item in value.items():
        if isinstance(item, dict):
            result[str(key)] = dict(item)
        else:
            result[str(key)] = {
                "value": item,
                "status": "confirmed",
                "source_turn_id": None,
                "updated_at": None,
            }
    return result


def _list_of_dicts(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _as_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None

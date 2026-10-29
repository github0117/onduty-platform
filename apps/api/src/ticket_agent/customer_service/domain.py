"""Conversation turn state machine.

A turn is the runtime transaction unit: one buyer message in, one answer (or
an explicit failure) out. The status column used to be free-form strings set
from three different code paths; this module is the single place that decides
which edges are legal, so an illegal jump fails loudly instead of silently
corrupting the conversation history.
"""

from __future__ import annotations

from enum import StrEnum


class TurnStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_TERMINAL = "FAILED_TERMINAL"
    CANCELLED = "CANCELLED"


TERMINAL_TURN_STATUSES: frozenset[TurnStatus] = frozenset(
    {
        TurnStatus.COMPLETED,
        TurnStatus.NEEDS_HUMAN,
        TurnStatus.FAILED_TERMINAL,
        TurnStatus.CANCELLED,
    }
)

# A retryable failure goes back to PENDING (not straight to RUNNING) so the
# reclaim/retry path is visible in the event log.
ALLOWED_TURN_TRANSITIONS: dict[TurnStatus, frozenset[TurnStatus]] = {
    TurnStatus.PENDING: frozenset(
        {
            TurnStatus.RUNNING,
            TurnStatus.FAILED_TERMINAL,
            TurnStatus.CANCELLED,
        }
    ),
    TurnStatus.RUNNING: frozenset(
        {
            TurnStatus.COMPLETED,
            TurnStatus.NEEDS_HUMAN,
            TurnStatus.FAILED_RETRYABLE,
            TurnStatus.FAILED_TERMINAL,
            TurnStatus.CANCELLED,
        }
    ),
    TurnStatus.FAILED_RETRYABLE: frozenset(
        {
            TurnStatus.PENDING,
            TurnStatus.FAILED_TERMINAL,
            TurnStatus.CANCELLED,
        }
    ),
    TurnStatus.COMPLETED: frozenset(),
    TurnStatus.NEEDS_HUMAN: frozenset(),
    TurnStatus.FAILED_TERMINAL: frozenset(),
    TurnStatus.CANCELLED: frozenset(),
}

# Old rows persisted the pre-state-machine vocabulary. The migration rewrites
# them, but parsing stays tolerant so a partially migrated database cannot
# crash the runtime.
_LEGACY_STATUS_ALIASES: dict[str, TurnStatus] = {
    "RECEIVED": TurnStatus.PENDING,
    "FAILED": TurnStatus.FAILED_RETRYABLE,
}


def parse_turn_status(value: str) -> TurnStatus:
    try:
        return TurnStatus(value)
    except ValueError:
        alias = _LEGACY_STATUS_ALIASES.get(value.upper())
        if alias is None:
            raise
        return alias


def is_terminal(status: TurnStatus) -> bool:
    return status in TERMINAL_TURN_STATUSES

"""Status vocabulary and legal edges for workflow runs and steps.

The executor owns every transition; the API only exposes replay, which is
limited to the two attention states. Anything not listed here is a bug.
"""

from enum import StrEnum


class WorkflowStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DEAD_LETTER = "DEAD_LETTER"


class StepStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DEAD_LETTER = "DEAD_LETTER"


ATTENTION_STATUSES = (WorkflowStatus.FAILED, WorkflowStatus.DEAD_LETTER)
REPLAYABLE_STATUSES = frozenset({WorkflowStatus.FAILED, WorkflowStatus.DEAD_LETTER})
TERMINAL_RUN_STATUSES = frozenset(
    {
        WorkflowStatus.SUCCEEDED,
        WorkflowStatus.FAILED,
        WorkflowStatus.DEAD_LETTER,
    }
)

ALLOWED_RUN_TRANSITIONS: dict[WorkflowStatus, frozenset[WorkflowStatus]] = {
    WorkflowStatus.PENDING: frozenset(
        {
            WorkflowStatus.RUNNING,
            WorkflowStatus.SUCCEEDED,
            WorkflowStatus.FAILED,
            WorkflowStatus.DEAD_LETTER,
        }
    ),
    WorkflowStatus.RUNNING: frozenset(
        {
            WorkflowStatus.PENDING,
            WorkflowStatus.SUCCEEDED,
            WorkflowStatus.FAILED,
            WorkflowStatus.DEAD_LETTER,
        }
    ),
    WorkflowStatus.SUCCEEDED: frozenset(),
    WorkflowStatus.FAILED: frozenset({WorkflowStatus.PENDING}),
    WorkflowStatus.DEAD_LETTER: frozenset({WorkflowStatus.PENDING}),
}

ALLOWED_STEP_TRANSITIONS: dict[StepStatus, frozenset[StepStatus]] = {
    StepStatus.PENDING: frozenset(
        {StepStatus.RUNNING, StepStatus.FAILED, StepStatus.DEAD_LETTER}
    ),
    StepStatus.RUNNING: frozenset(
        {
            StepStatus.SUCCEEDED,
            StepStatus.PENDING,
            StepStatus.FAILED,
            StepStatus.DEAD_LETTER,
        }
    ),
    StepStatus.SUCCEEDED: frozenset(),
    StepStatus.FAILED: frozenset({StepStatus.PENDING}),
    StepStatus.DEAD_LETTER: frozenset({StepStatus.PENDING}),
}


def can_transition_run(current: str, target: str) -> bool:
    try:
        allowed = ALLOWED_RUN_TRANSITIONS[WorkflowStatus(current)]
        return WorkflowStatus(target) in allowed
    except ValueError:
        return False


def can_transition_step(current: str, target: str) -> bool:
    try:
        allowed = ALLOWED_STEP_TRANSITIONS[StepStatus(current)]
        return StepStatus(target) in allowed
    except ValueError:
        return False

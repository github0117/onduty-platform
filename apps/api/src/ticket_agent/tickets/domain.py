from enum import StrEnum


class TicketStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_USER = "WAITING_USER"
    WAITING_HUMAN = "WAITING_HUMAN"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class WorkflowState(StrEnum):
    RECEIVED = "RECEIVED"
    CLASSIFYING = "CLASSIFYING"
    RISK_EVALUATED = "RISK_EVALUATED"
    ROUTING = "ROUTING"
    DRAFTING = "DRAFTING"
    PENDING_REVIEW = "PENDING_REVIEW"
    SYNCING = "SYNCING"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    TAKEN_OVER = "TAKEN_OVER"
    COMPLETED = "COMPLETED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_TERMINAL = "FAILED_TERMINAL"


class RiskLevel(StrEnum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"


class Priority(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


TERMINAL_WORKFLOW_STATES = {
    WorkflowState.TAKEN_OVER,
    WorkflowState.COMPLETED,
    WorkflowState.FAILED_TERMINAL,
}

# Every state change must follow an explicit edge. Automated workflows may not
# leave TERMINAL_WORKFLOW_STATES; operator-driven flows (takeover, manual
# reply, reopening a completed conversation) pass allow_terminal=True.
ALLOWED_WORKFLOW_TRANSITIONS: dict[
    WorkflowState, frozenset[WorkflowState]
] = {
    WorkflowState.RECEIVED: frozenset(
        {
            WorkflowState.CLASSIFYING,
            WorkflowState.NEEDS_HUMAN,
            WorkflowState.PENDING_REVIEW,
            WorkflowState.SYNCING,
            WorkflowState.TAKEN_OVER,
            WorkflowState.COMPLETED,
        }
    ),
    WorkflowState.CLASSIFYING: frozenset(
        {
            WorkflowState.RISK_EVALUATED,
            WorkflowState.NEEDS_HUMAN,
            WorkflowState.PENDING_REVIEW,
            WorkflowState.SYNCING,
            WorkflowState.TAKEN_OVER,
            WorkflowState.COMPLETED,
        }
    ),
    WorkflowState.RISK_EVALUATED: frozenset(
        {
            WorkflowState.ROUTING,
            WorkflowState.NEEDS_HUMAN,
            WorkflowState.PENDING_REVIEW,
            WorkflowState.SYNCING,
            WorkflowState.TAKEN_OVER,
            WorkflowState.COMPLETED,
        }
    ),
    WorkflowState.ROUTING: frozenset(
        {
            WorkflowState.DRAFTING,
            WorkflowState.NEEDS_HUMAN,
            WorkflowState.PENDING_REVIEW,
            WorkflowState.SYNCING,
            WorkflowState.TAKEN_OVER,
            WorkflowState.COMPLETED,
        }
    ),
    WorkflowState.DRAFTING: frozenset(
        {
            WorkflowState.PENDING_REVIEW,
            WorkflowState.NEEDS_HUMAN,
            WorkflowState.SYNCING,
            WorkflowState.TAKEN_OVER,
            WorkflowState.COMPLETED,
        }
    ),
    WorkflowState.PENDING_REVIEW: frozenset(
        {
            WorkflowState.SYNCING,
            WorkflowState.NEEDS_HUMAN,
            WorkflowState.TAKEN_OVER,
            WorkflowState.COMPLETED,
        }
    ),
    WorkflowState.SYNCING: frozenset(
        {
            WorkflowState.COMPLETED,
            WorkflowState.NEEDS_HUMAN,
            WorkflowState.FAILED_RETRYABLE,
            WorkflowState.FAILED_TERMINAL,
            WorkflowState.TAKEN_OVER,
        }
    ),
    WorkflowState.NEEDS_HUMAN: frozenset(
        {
            WorkflowState.RECEIVED,
            WorkflowState.PENDING_REVIEW,
            WorkflowState.SYNCING,
            WorkflowState.TAKEN_OVER,
            WorkflowState.COMPLETED,
            WorkflowState.FAILED_RETRYABLE,
            WorkflowState.FAILED_TERMINAL,
        }
    ),
    WorkflowState.TAKEN_OVER: frozenset(
        {
            WorkflowState.RECEIVED,
            WorkflowState.NEEDS_HUMAN,
            WorkflowState.PENDING_REVIEW,
            WorkflowState.COMPLETED,
        }
    ),
    WorkflowState.COMPLETED: frozenset({WorkflowState.RECEIVED}),
    WorkflowState.FAILED_RETRYABLE: frozenset(
        {
            WorkflowState.SYNCING,
            WorkflowState.NEEDS_HUMAN,
            WorkflowState.TAKEN_OVER,
            WorkflowState.COMPLETED,
            WorkflowState.FAILED_TERMINAL,
        }
    ),
    WorkflowState.FAILED_TERMINAL: frozenset(),
}


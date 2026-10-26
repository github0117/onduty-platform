from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.redaction import (
    redact_sensitive_data,
    redact_sensitive_text,
)
from ticket_agent.tools.models import ToolCall
from ticket_agent.tools.registry import ToolDefinition, ToolPermissionError, tool_registry
from ticket_agent.tools.schemas import validate_tool_payload


class ToolExecutionService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def begin(
        self,
        *,
        employee: DigitalEmployee,
        tool_key: str,
        payload: dict[str, Any],
        correlation_id: str,
        ticket_id: UUID | None = None,
        human_approved: bool = False,
        policy_approved: bool = False,
    ) -> tuple[ToolCall, ToolDefinition, dict[str, Any]]:
        try:
            definition = tool_registry.authorize(
                employee,
                tool_key,
                human_approved=human_approved,
                policy_approved=policy_approved,
            )
            validated = validate_tool_payload(tool_key, payload)
        except ToolPermissionError:
            self.record_denied(
                employee=employee,
                tool_key=tool_key,
                payload=payload,
                correlation_id=correlation_id,
                ticket_id=ticket_id,
                reason_code="TOOL_PERMISSION_DENIED",
            )
            raise
        except (ValidationError, ValueError) as exc:
            call = self._new_call(
                employee=employee,
                tool_key=tool_key,
                definition=tool_registry.definition(tool_key),
                payload=payload,
                correlation_id=correlation_id,
                ticket_id=ticket_id,
                status="FAILED",
            )
            call.error_code = "TOOL_SCHEMA_VALIDATION_FAILED"
            call.error_message = str(exc)[:2000]
            call.completed_at = datetime.now(UTC)
            self.session.add(call)
            raise ApiProblem(
                status_code=422,
                code="TOOL_SCHEMA_VALIDATION_FAILED",
                title="Tool input is invalid",
                detail=f"Tool '{tool_key}' received an invalid input payload.",
            ) from exc

        call = self._new_call(
            employee=employee,
            tool_key=tool_key,
            definition=definition,
            payload=validated,
            correlation_id=correlation_id,
            ticket_id=ticket_id,
            status="STARTED",
        )
        self.session.add(call)
        self.session.flush()
        return call, definition, validated

    def succeed(self, call: ToolCall, summary: dict[str, Any]) -> None:
        call.status = "SUCCEEDED"
        call.response_summary = _redact_payload(summary)
        call.completed_at = datetime.now(UTC)

    def begin_external(
        self,
        *,
        employee: DigitalEmployee,
        definition: ToolDefinition,
        payload: dict[str, Any],
        correlation_id: str,
        ticket_id: UUID | None = None,
    ) -> ToolCall:
        call = self._new_call(
            employee=employee,
            tool_key=definition.key,
            definition=definition,
            payload=payload,
            correlation_id=correlation_id,
            ticket_id=ticket_id,
            status="STARTED",
        )
        self.session.add(call)
        self.session.flush()
        return call

    def fail(
        self,
        call: ToolCall,
        *,
        error_code: str,
        error_message: str,
    ) -> None:
        call.status = "FAILED"
        call.error_code = error_code
        call.error_message = redact_sensitive_text(error_message)[:2000]
        call.completed_at = datetime.now(UTC)

    def record_denied(
        self,
        *,
        employee: DigitalEmployee,
        tool_key: str,
        payload: dict[str, Any],
        correlation_id: str,
        ticket_id: UUID | None,
        reason_code: str,
    ) -> ToolCall:
        try:
            definition = tool_registry.definition(tool_key)
        except ToolPermissionError:
            definition = ToolDefinition(
                key=tool_key,
                name=tool_key,
                risk_level="UNKNOWN",
                action_type="UNKNOWN",
            )
        call = self._new_call(
            employee=employee,
            tool_key=tool_key,
            definition=definition,
            payload=payload,
            correlation_id=correlation_id,
            ticket_id=ticket_id,
            status="DENIED",
        )
        call.error_code = reason_code
        call.completed_at = datetime.now(UTC)
        self.session.add(call)
        self.session.flush()
        return call

    def _new_call(
        self,
        *,
        employee: DigitalEmployee,
        tool_key: str,
        definition: ToolDefinition,
        payload: dict[str, Any],
        correlation_id: str,
        ticket_id: UUID | None,
        status: str,
    ) -> ToolCall:
        return ToolCall(
            employee_id=employee.id,
            ticket_id=ticket_id,
            tool_key=tool_key,
            action_type=definition.action_type,
            risk_level=definition.risk_level,
            status=status,
            correlation_id=correlation_id,
            request_payload=_redact_payload(payload),
        )


def _redact_payload(value: Any) -> Any:
    return redact_sensitive_data(value)


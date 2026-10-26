from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ticket_agent.audit.service import record_audit
from ticket_agent.digital_employees.service import DigitalEmployeeService
from ticket_agent.mcp_connectors.models import (
    McpActionIncident,
    McpToolApproval,
)
from ticket_agent.mcp_connectors.schemas import (
    McpToolApprovalDecision,
    McpToolApprovalList,
    McpToolApprovalView,
)
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.redaction import redact_sensitive_data

REUSABLE_STATUSES = ("PENDING", "EXECUTING", "SUCCEEDED", "FAILED")


class McpToolApprovalService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def request(
        self,
        *,
        business_unit_id: str,
        employee_id: UUID,
        connector_id: UUID,
        connector_code: str,
        tool_name: str,
        tool_id: str,
        arguments: dict[str, object],
        requested_by: str,
        correlation_id: str,
        ticket_id: UUID | None,
        conversation_id: UUID | None,
        reason: str,
        request_tool_call_id: UUID | None,
        required_role: str,
        policy: dict[str, object],
    ) -> tuple[McpToolApproval, bool]:
        fingerprint = _fingerprint(
            employee_id=employee_id,
            connector_id=connector_id,
            tool_id=tool_id,
            ticket_id=ticket_id,
            arguments=arguments,
        )
        existing = self._find_reusable(
            fingerprint=fingerprint,
            business_unit_id=business_unit_id,
        )
        if existing is not None:
            return self._reuse(
                existing,
                employee_id=employee_id,
                tool_id=tool_id,
                correlation_id=correlation_id,
            )

        approval = McpToolApproval(
            business_unit_id=business_unit_id,
            employee_id=employee_id,
            connector_id=connector_id,
            ticket_id=ticket_id,
            conversation_id=conversation_id,
            tool_id=tool_id,
            connector_code=connector_code,
            tool_name=tool_name,
            arguments_json=redact_sensitive_data(arguments),
            execution_arguments_json=arguments,
            required_role=required_role,
            policy_json=policy,
            request_fingerprint=fingerprint,
            status="PENDING",
            requested_by=requested_by,
            request_correlation_id=correlation_id,
            reason=reason[:2000],
            request_tool_call_id=request_tool_call_id,
        )
        try:
            with self.session.begin_nested():
                self.session.add(approval)
                self.session.flush()
        except IntegrityError:
            # Another request with the same fingerprint won the race. The
            # partial unique index keeps the active approval single.
            existing = self._find_reusable(
                fingerprint=fingerprint,
                business_unit_id=business_unit_id,
            )
            if existing is None:
                raise
            return self._reuse(
                existing,
                employee_id=employee_id,
                tool_id=tool_id,
                correlation_id=correlation_id,
            )
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="mcp_tool_approval.requested",
            actor_type="DIGITAL_EMPLOYEE",
            actor_id=str(employee_id),
            resource_type="mcp_tool_approval",
            resource_id=approval.id,
            action="request_approval",
            decision="PENDING",
            on_behalf_of=requested_by,
            payload={
                "tool_id": tool_id,
                "ticket_id": str(ticket_id) if ticket_id else None,
                "argument_keys": sorted(arguments),
                "required_role": required_role,
                "policy_reason": policy.get("reason_code"),
            },
        )
        self.session.commit()
        self.session.refresh(approval)
        return approval, False

    def _find_reusable(
        self,
        *,
        fingerprint: str,
        business_unit_id: str,
    ) -> McpToolApproval | None:
        return self.session.scalar(
            select(McpToolApproval)
            .where(
                McpToolApproval.business_unit_id == business_unit_id,
                McpToolApproval.request_fingerprint == fingerprint,
                McpToolApproval.status.in_(REUSABLE_STATUSES),
            )
            .order_by(McpToolApproval.created_at.desc())
            .limit(1)
        )

    def _reuse(
        self,
        approval: McpToolApproval,
        *,
        employee_id: UUID,
        tool_id: str,
        correlation_id: str,
    ) -> tuple[McpToolApproval, bool]:
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="mcp_tool_approval.reused",
            actor_type="DIGITAL_EMPLOYEE",
            actor_id=str(employee_id),
            resource_type="mcp_tool_approval",
            resource_id=approval.id,
            action="reuse_approval",
            decision="OBSERVED",
            payload={
                "tool_id": tool_id,
                "status": approval.status,
            },
        )
        self.session.commit()
        return approval, True

    def list(
        self,
        *,
        business_unit_id: str,
        status: str | None,
        limit: int,
    ) -> McpToolApprovalList:
        filters = [McpToolApproval.business_unit_id == business_unit_id]
        if status:
            filters.append(McpToolApproval.status == status)
        total = self.session.scalar(
            select(func.count())
            .select_from(McpToolApproval)
            .where(*filters)
        ) or 0
        items = list(
            self.session.scalars(
                select(McpToolApproval)
                .where(*filters)
                .order_by(McpToolApproval.created_at.desc())
                .limit(limit)
            ).all()
        )
        return McpToolApprovalList(
            items=[self.view(item) for item in items],
            total=total,
        )

    def get(self, approval_id: UUID) -> McpToolApproval:
        approval = self.session.get(McpToolApproval, approval_id)
        if approval is None:
            raise ApiProblem(
                status_code=404,
                code="MCP_APPROVAL_NOT_FOUND",
                title="MCP approval not found",
                detail=f"MCP approval {approval_id} does not exist.",
            )
        return approval

    def decide(
        self,
        approval_id: UUID,
        payload: McpToolApprovalDecision,
        *,
        actor_id: str,
        actor_role: str,
        correlation_id: str,
    ) -> McpToolApprovalView:
        approval = self.session.scalar(
            select(McpToolApproval)
            .where(McpToolApproval.id == approval_id)
            .with_for_update()
        )
        if approval is None:
            raise ApiProblem(
                status_code=404,
                code="MCP_APPROVAL_NOT_FOUND",
                title="MCP approval not found",
                detail=f"MCP approval {approval_id} does not exist.",
            )
        if approval.version != payload.expected_version:
            raise ApiProblem(
                status_code=409,
                code="MCP_APPROVAL_VERSION_CONFLICT",
                title="MCP approval changed",
                detail="Reload the approval before making another decision.",
                retryable=True,
            )
        if approval.status != "PENDING":
            raise ApiProblem(
                status_code=409,
                code="MCP_APPROVAL_NOT_PENDING",
                title="MCP approval is not pending",
                detail=f"The approval is already {approval.status}.",
            )
        if actor_role not in {"supervisor", "admin"}:
            raise ApiProblem(
                status_code=403,
                code="MCP_APPROVAL_ROLE_REQUIRED",
                title="Supervisor approval required",
                detail="Only a supervisor or administrator can decide this approval.",
            )
        if approval.required_role == "admin" and actor_role != "admin":
            raise ApiProblem(
                status_code=403,
                code="MCP_APPROVAL_ADMIN_REQUIRED",
                title="Administrator approval required",
                detail="This action exceeds the supervisor approval limit.",
            )
        if actor_id == approval.requested_by:
            raise ApiProblem(
                status_code=403,
                code="MCP_APPROVAL_SELF_APPROVAL_DENIED",
                title="Independent approver required",
                detail="The requester cannot approve or reject their own MCP write.",
            )

        now = datetime.now(UTC)
        approval.decided_by = actor_id
        approval.decision_note = redact_sensitive_data(payload.note)
        approval.decided_at = now
        approval.version += 1
        if payload.decision == "REJECT":
            approval.status = "REJECTED"
            approval.completed_at = now
            record_audit(
                self.session,
                correlation_id=correlation_id,
                event_type="mcp_tool_approval.rejected",
                actor_type="USER",
                actor_id=actor_id,
                resource_type="mcp_tool_approval",
                resource_id=approval.id,
                action="reject",
                decision="REJECTED",
                payload={
                    "tool_id": approval.tool_id,
                    "requested_by": approval.requested_by,
                },
            )
            self.session.commit()
            self.session.refresh(approval)
            return self.view(approval)

        approval.status = "EXECUTING"
        approval.execution_correlation_id = correlation_id
        approval.execution_started_at = now
        self.session.commit()
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="mcp_tool_approval.approved",
            actor_type="USER",
            actor_id=actor_id,
            resource_type="mcp_tool_approval",
            resource_id=approval.id,
            action="approve",
            decision="APPROVED",
            payload={
                "tool_id": approval.tool_id,
                "requested_by": approval.requested_by,
            },
        )
        self.session.commit()

        from ticket_agent.mcp_connectors.runtime import McpToolRuntime

        try:
            employee = DigitalEmployeeService(self.session).get(
                approval.employee_id
            )
            result = McpToolRuntime(self.session).execute(
                employee=employee,
                tool_id=approval.tool_id,
                arguments=dict(
                    approval.execution_arguments_json
                    or approval.arguments_json
                ),
                correlation_id=correlation_id,
                ticket_id=approval.ticket_id,
                requested_by=approval.requested_by,
                conversation_id=approval.conversation_id,
                reason=approval.reason,
                approved_by=actor_id,
                approval_id=approval.id,
            )
            approval.execution_tool_call_id = result.tool_call_id
            if result.status == "SUCCEEDED":
                approval.status = "SUCCEEDED"
                approval.result_json = {
                    "text": result.text,
                    "tool_id": result.tool_id,
                    "duration_ms": result.duration_ms,
                }
                approval.error_code = None
                approval.error_message = None
            else:
                approval.status = "FAILED"
                approval.error_code = result.error_code or "MCP_TOOL_CALL_FAILED"
                approval.error_message = result.error_message
                from ticket_agent.mcp_connectors.incidents import (
                    McpActionIncidentService,
                )

                McpActionIncidentService(self.session).record_failure(
                    approval=approval,
                    error_code=approval.error_code,
                    error_message=approval.error_message,
                    correlation_id=correlation_id,
                )
            self._sync_compensation_incident(
                approval,
                succeeded=result.status == "SUCCEEDED",
                result={
                    "text": result.text,
                    "error_code": result.error_code,
                    "error_message": result.error_message,
                    "duration_ms": result.duration_ms,
                },
            )
            approval.completed_at = datetime.now(UTC)
            approval.version += 1
            record_audit(
                self.session,
                correlation_id=correlation_id,
                event_type=f"mcp_tool_approval.{approval.status.lower()}",
                actor_type="SYSTEM",
                actor_id="mcp_tool_runtime",
                resource_type="mcp_tool_approval",
                resource_id=approval.id,
                action="execute_approved_tool",
                decision=approval.status,
                on_behalf_of=actor_id,
                payload={
                    "tool_id": approval.tool_id,
                    "tool_call_id": str(result.tool_call_id),
                    "duration_ms": result.duration_ms,
                },
            )
            self.session.commit()
        except Exception as exc:
            approval.status = "FAILED"
            approval.error_code = "MCP_APPROVED_EXECUTION_FAILED"
            approval.error_message = _safe_error(exc)
            approval.completed_at = datetime.now(UTC)
            approval.version += 1
            from ticket_agent.mcp_connectors.incidents import (
                McpActionIncidentService,
            )

            McpActionIncidentService(self.session).record_failure(
                approval=approval,
                error_code=approval.error_code,
                error_message=approval.error_message,
                correlation_id=correlation_id,
            )
            self._sync_compensation_incident(
                approval,
                succeeded=False,
                result={
                    "error_code": approval.error_code,
                    "error_message": approval.error_message,
                },
            )
            self.session.commit()
        self.session.refresh(approval)
        return self.view(approval)

    @staticmethod
    def view(approval: McpToolApproval) -> McpToolApprovalView:
        return McpToolApprovalView(
            id=approval.id,
            business_unit_id=approval.business_unit_id,
            employee_id=approval.employee_id,
            connector_id=approval.connector_id,
            ticket_id=approval.ticket_id,
            conversation_id=approval.conversation_id,
            tool_id=approval.tool_id,
            connector_code=approval.connector_code,
            tool_name=approval.tool_name,
            arguments=approval.arguments_json,
            required_role=approval.required_role,
            policy=approval.policy_json,
            status=approval.status,
            requested_by=approval.requested_by,
            request_correlation_id=approval.request_correlation_id,
            reason=approval.reason,
            decided_by=approval.decided_by,
            decision_note=approval.decision_note,
            result=approval.result_json,
            error_code=approval.error_code,
            error_message=approval.error_message,
            version=approval.version,
            decided_at=approval.decided_at,
            execution_started_at=approval.execution_started_at,
            completed_at=approval.completed_at,
            created_at=approval.created_at,
            updated_at=approval.updated_at,
        )

    def _sync_compensation_incident(
        self,
        approval: McpToolApproval,
        *,
        succeeded: bool,
        result: dict[str, object],
    ) -> None:
        incident = self.session.scalar(
            select(McpActionIncident).where(
                McpActionIncident.compensation_approval_id == approval.id
            )
        )
        if incident is None:
            return
        incident.compensation_status = (
            "SUCCEEDED" if succeeded else "FAILED"
        )
        incident.compensation_result_json = result
        incident.version += 1


def _fingerprint(
    *,
    employee_id: UUID,
    connector_id: UUID,
    tool_id: str,
    ticket_id: UUID | None,
    arguments: dict[str, object],
) -> str:
    canonical = json.dumps(
        {
            "employee_id": str(employee_id),
            "connector_id": str(connector_id),
            "tool_id": tool_id,
            "ticket_id": str(ticket_id) if ticket_id else None,
            "arguments": arguments,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_error(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return str(redact_sensitive_data(text))[:2000]

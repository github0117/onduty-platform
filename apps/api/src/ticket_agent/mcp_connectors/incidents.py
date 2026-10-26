from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ticket_agent.audit.service import record_audit
from ticket_agent.digital_employees.service import DigitalEmployeeService
from ticket_agent.mcp_connectors.models import (
    McpActionIncident,
    McpToolApproval,
)
from ticket_agent.mcp_connectors.schemas import (
    McpActionIncidentAction,
    McpActionIncidentCompensation,
    McpActionIncidentList,
    McpActionIncidentReconcile,
    McpActionIncidentResolve,
    McpActionIncidentView,
)
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.redaction import redact_sensitive_data
from ticket_agent.shared.settings import get_settings


class McpActionIncidentService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record_failure(
        self,
        *,
        approval: McpToolApproval,
        error_code: str,
        error_message: str | None,
        correlation_id: str,
    ) -> McpActionIncident:
        existing = self.session.scalar(
            select(McpActionIncident).where(
                McpActionIncident.approval_id == approval.id
            )
        )
        if existing is not None:
            return existing
        failure_class, required_action = _failure_guidance(error_code)
        incident = McpActionIncident(
            business_unit_id=approval.business_unit_id,
            approval_id=approval.id,
            employee_id=approval.employee_id,
            ticket_id=approval.ticket_id,
            conversation_id=approval.conversation_id,
            tool_id=approval.tool_id,
            failure_class=failure_class,
            status="OPEN",
            error_code=error_code,
            error_message=(
                str(redact_sensitive_data(error_message))[:2000]
                if error_message
                else None
            ),
            required_action=required_action,
        )
        self.session.add(incident)
        self.session.flush()
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="mcp_action_incident.opened",
            actor_type="SYSTEM",
            actor_id="mcp_tool_runtime",
            resource_type="mcp_action_incident",
            resource_id=incident.id,
            action="open_incident",
            decision="OPEN",
            payload={
                "approval_id": str(approval.id),
                "tool_id": approval.tool_id,
                "failure_class": failure_class,
                "error_code": error_code,
            },
        )
        return incident

    def list(
        self,
        *,
        business_unit_id: str,
        status: str | None,
        limit: int,
    ) -> McpActionIncidentList:
        filters = [McpActionIncident.business_unit_id == business_unit_id]
        if status:
            filters.append(McpActionIncident.status == status)
        total = self.session.scalar(
            select(func.count())
            .select_from(McpActionIncident)
            .where(*filters)
        ) or 0
        items = list(
            self.session.scalars(
                select(McpActionIncident)
                .where(*filters)
                .order_by(McpActionIncident.created_at.desc())
                .limit(limit)
            ).all()
        )
        return McpActionIncidentList(
            items=[self.view(item) for item in items],
            total=total,
        )

    def get(self, incident_id: UUID) -> McpActionIncident:
        incident = self.session.get(McpActionIncident, incident_id)
        if incident is None:
            raise ApiProblem(
                status_code=404,
                code="MCP_INCIDENT_NOT_FOUND",
                title="MCP incident not found",
                detail=f"MCP incident {incident_id} does not exist.",
            )
        return incident

    def acknowledge(
        self,
        incident_id: UUID,
        payload: McpActionIncidentAction,
        *,
        actor_id: str,
        correlation_id: str,
    ) -> McpActionIncidentView:
        incident = self._get_for_update(incident_id)
        self._check_version(incident, payload.expected_version)
        if incident.status != "OPEN":
            raise _invalid_state(incident)
        now = datetime.now(UTC)
        incident.status = "ACKNOWLEDGED"
        incident.assigned_to = actor_id
        incident.resolution_note = (
            str(redact_sensitive_data(payload.note))[:4000]
            if payload.note
            else None
        )
        incident.acknowledged_at = now
        incident.version += 1
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="mcp_action_incident.acknowledged",
            actor_type="USER",
            actor_id=actor_id,
            resource_type="mcp_action_incident",
            resource_id=incident.id,
            action="acknowledge",
            decision="ACKNOWLEDGED",
            payload={"approval_id": str(incident.approval_id)},
        )
        self.session.commit()
        self.session.refresh(incident)
        return self.view(incident)

    def resolve(
        self,
        incident_id: UUID,
        payload: McpActionIncidentResolve,
        *,
        actor_id: str,
        correlation_id: str,
    ) -> McpActionIncidentView:
        if not payload.note.strip():
            raise ApiProblem(
                status_code=422,
                code="MCP_INCIDENT_RESOLUTION_NOTE_REQUIRED",
                title="Resolution note required",
                detail="Record how the external result was verified before resolving.",
            )
        incident = self._get_for_update(incident_id)
        self._check_version(incident, payload.expected_version)
        if incident.status not in {"OPEN", "ACKNOWLEDGED"}:
            raise _invalid_state(incident)
        if (
            payload.outcome == "EXECUTED_INCORRECTLY"
            and incident.compensation_status != "SUCCEEDED"
        ):
            raise ApiProblem(
                status_code=409,
                code="MCP_INCIDENT_COMPENSATION_REQUIRED",
                title="Compensation is required",
                detail=(
                    "An incorrectly executed action cannot be closed until "
                    "a compensation approval succeeds."
                ),
            )
        now = datetime.now(UTC)
        incident.status = "RESOLVED"
        incident.assigned_to = incident.assigned_to or actor_id
        incident.resolution_note = str(
            redact_sensitive_data(payload.note)
        )[:4000]
        incident.resolution_outcome = payload.outcome
        incident.resolved_at = now
        incident.version += 1
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="mcp_action_incident.resolved",
            actor_type="USER",
            actor_id=actor_id,
            resource_type="mcp_action_incident",
            resource_id=incident.id,
            action="resolve",
            decision="RESOLVED",
            payload={"approval_id": str(incident.approval_id)},
        )
        self.session.commit()
        self.session.refresh(incident)
        return self.view(incident)

    def reconcile(
        self,
        incident_id: UUID,
        payload: McpActionIncidentReconcile,
        *,
        actor_id: str,
        correlation_id: str,
    ) -> McpActionIncidentView:
        incident = self._get_for_update(incident_id)
        self._check_version(incident, payload.expected_version)
        if incident.status == "RESOLVED":
            raise _invalid_state(incident)
        from ticket_agent.mcp_connectors.runtime import McpToolRuntime

        employee = DigitalEmployeeService(self.session).get(
            incident.employee_id
        )
        runtime = McpToolRuntime(self.session)
        targets = runtime.available_tools(employee)
        target = _select_reconciliation_tool(
            targets=targets,
            original_tool_id=incident.tool_id,
            requested_tool_id=payload.tool_id,
        )
        if target is None:
            raise ApiProblem(
                status_code=409,
                code="MCP_RECONCILIATION_TOOL_NOT_CONFIGURED",
                title="Reconciliation tool is not configured",
                detail=(
                    "Bind an allowed read-only MCP tool for this action "
                    "before reconciling the incident."
                ),
            )
        approval = self.session.get(McpToolApproval, incident.approval_id)
        source_arguments = (
            dict(approval.execution_arguments_json or approval.arguments_json)
            if approval
            else {}
        )
        arguments = _arguments_for_tool(target.input_schema, source_arguments)
        result = runtime.execute(
            employee=employee,
            tool_id=target.tool_id,
            arguments=arguments,
            correlation_id=correlation_id,
            ticket_id=incident.ticket_id,
        )
        incident.reconciliation_attempts += 1
        incident.reconciliation_tool_id = target.tool_id
        incident.reconciliation_arguments_json = arguments
        incident.reconciliation_tool_call_id = result.tool_call_id
        incident.last_reconciled_at = datetime.now(UTC)
        if result.status == "SUCCEEDED":
            incident.reconciliation_status = "SUCCEEDED"
            incident.reconciliation_result_json = {
                "text": result.text,
                "duration_ms": result.duration_ms,
            }
        else:
            incident.reconciliation_status = "FAILED"
            incident.reconciliation_result_json = {
                "error_code": result.error_code,
                "error_message": result.error_message,
            }
        incident.version += 1
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="mcp_action_incident.reconciled",
            actor_type="USER" if actor_id != "system.reconciliation" else "SYSTEM",
            actor_id=actor_id,
            resource_type="mcp_action_incident",
            resource_id=incident.id,
            action="reconcile",
            decision=incident.reconciliation_status,
            payload={
                "approval_id": str(incident.approval_id),
                "reconciliation_tool_id": target.tool_id,
            },
        )
        self.session.commit()
        self.session.refresh(incident)
        return self.view(incident)

    def request_compensation(
        self,
        incident_id: UUID,
        payload: McpActionIncidentCompensation,
        *,
        actor_id: str,
        correlation_id: str,
    ) -> McpActionIncidentView:
        incident = self._get_for_update(incident_id)
        self._check_version(incident, payload.expected_version)
        if incident.status == "RESOLVED":
            raise _invalid_state(incident)
        if incident.compensation_status in {"PENDING_APPROVAL", "EXECUTING", "SUCCEEDED"}:
            raise ApiProblem(
                status_code=409,
                code="MCP_INCIDENT_COMPENSATION_ALREADY_EXISTS",
                title="Compensation already exists",
                detail=(
                    "This incident already has an active or successful "
                    "compensation request."
                ),
            )
        from ticket_agent.mcp_connectors.runtime import McpToolRuntime

        employee = DigitalEmployeeService(self.session).get(
            incident.employee_id
        )
        runtime = McpToolRuntime(self.session)
        target = _select_compensation_tool(
            targets=runtime.available_tools(employee),
            original_tool_id=incident.tool_id,
            requested_tool_id=payload.tool_id,
        )
        if target is None:
            raise ApiProblem(
                status_code=409,
                code="MCP_COMPENSATION_TOOL_NOT_CONFIGURED",
                title="Compensation tool is not configured",
                detail=(
                    "Bind an allowed write tool named with reverse or "
                    "compensate before requesting compensation."
                ),
            )
        result = runtime.execute(
            employee=employee,
            tool_id=target.tool_id,
            arguments=payload.arguments,
            correlation_id=correlation_id,
            ticket_id=incident.ticket_id,
            requested_by=actor_id,
            conversation_id=incident.conversation_id,
            reason=payload.note,
        )
        if result.approval_id is None:
            raise ApiProblem(
                status_code=409,
                code="MCP_COMPENSATION_APPROVAL_NOT_CREATED",
                title="Compensation approval was not created",
                detail=result.error_message or result.error_code or "Unknown policy error.",
            )
        incident.compensation_tool_id = target.tool_id
        incident.compensation_approval_id = result.approval_id
        incident.compensation_status = "PENDING_APPROVAL"
        incident.version += 1
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="mcp_action_incident.compensation_requested",
            actor_type="USER",
            actor_id=actor_id,
            resource_type="mcp_action_incident",
            resource_id=incident.id,
            action="request_compensation",
            decision="PENDING_APPROVAL",
            payload={
                "approval_id": str(result.approval_id),
                "tool_id": target.tool_id,
            },
        )
        self.session.commit()
        self.session.refresh(incident)
        return self.view(incident)

    def reconcile_open_incidents(self, *, limit: int) -> int:
        incidents = list(
            self.session.scalars(
                select(McpActionIncident)
                .where(
                    McpActionIncident.failure_class == "EXECUTION_UNKNOWN",
                    McpActionIncident.status.in_(("OPEN", "ACKNOWLEDGED")),
                    McpActionIncident.reconciliation_attempts
                    < get_settings().mcp_reconciliation_max_attempts,
                )
                .order_by(McpActionIncident.created_at)
                .limit(limit)
            ).all()
        )
        reconciled = 0
        for incident in incidents:
            try:
                self.reconcile(
                    incident.id,
                    McpActionIncidentReconcile(
                        expected_version=incident.version,
                    ),
                    actor_id="system.reconciliation",
                    correlation_id=f"reconcile:{incident.id}",
                )
                reconciled += 1
            except ApiProblem:
                continue
        return reconciled

    def _get_for_update(self, incident_id: UUID) -> McpActionIncident:
        incident = self.session.scalar(
            select(McpActionIncident)
            .where(McpActionIncident.id == incident_id)
            .with_for_update()
        )
        if incident is None:
            raise ApiProblem(
                status_code=404,
                code="MCP_INCIDENT_NOT_FOUND",
                title="MCP incident not found",
                detail=f"MCP incident {incident_id} does not exist.",
            )
        return incident

    @staticmethod
    def _check_version(
        incident: McpActionIncident,
        expected_version: int,
    ) -> None:
        if incident.version != expected_version:
            raise ApiProblem(
                status_code=409,
                code="MCP_INCIDENT_VERSION_CONFLICT",
                title="MCP incident changed",
                detail="Reload the incident before continuing.",
                retryable=True,
            )

    @staticmethod
    def view(incident: McpActionIncident) -> McpActionIncidentView:
        return McpActionIncidentView(
            id=incident.id,
            business_unit_id=incident.business_unit_id,
            approval_id=incident.approval_id,
            employee_id=incident.employee_id,
            ticket_id=incident.ticket_id,
            conversation_id=incident.conversation_id,
            tool_id=incident.tool_id,
            failure_class=incident.failure_class,
            status=incident.status,
            error_code=incident.error_code,
            error_message=incident.error_message,
            required_action=incident.required_action,
            assigned_to=incident.assigned_to,
            resolution_note=incident.resolution_note,
            resolution_outcome=incident.resolution_outcome,
            reconciliation_status=incident.reconciliation_status,
            reconciliation_tool_id=incident.reconciliation_tool_id,
            reconciliation_arguments=incident.reconciliation_arguments_json,
            reconciliation_result=incident.reconciliation_result_json,
            reconciliation_tool_call_id=incident.reconciliation_tool_call_id,
            reconciliation_attempts=incident.reconciliation_attempts,
            last_reconciled_at=incident.last_reconciled_at,
            compensation_tool_id=incident.compensation_tool_id,
            compensation_approval_id=incident.compensation_approval_id,
            compensation_status=incident.compensation_status,
            compensation_result=incident.compensation_result_json,
            version=incident.version,
            acknowledged_at=incident.acknowledged_at,
            resolved_at=incident.resolved_at,
            created_at=incident.created_at,
            updated_at=incident.updated_at,
        )


def _failure_guidance(error_code: str) -> tuple[str, str]:
    if error_code == "MCP_TOOL_REJECTED":
        return (
            "REMOTE_REJECTED",
            "外部系统明确拒绝。核对拒因、订单和业务条件后再重新申请。",
        )
    if error_code == "MCP_TOOL_CALL_FAILED":
        return (
            "EXECUTION_UNKNOWN",
            "外部执行结果不确定。必须先在订单或资金系统核对实际结果，"
            "确认未执行后才能重新申请，禁止自动重试。",
        )
    return (
        "PRE_EXECUTION",
        "写工具未确认开始执行。核对配置和员工授权后，重新发起审批。",
    )


def _select_reconciliation_tool(
    *,
    targets: list[Any],
    original_tool_id: str,
    requested_tool_id: str | None,
) -> Any | None:
    read_targets = [target for target in targets if not target.is_write]
    if requested_tool_id:
        return next(
            (
                target
                for target in read_targets
                if target.tool_id == requested_tool_id
            ),
            None,
        )
    original_name = original_tool_id.rsplit(".", 1)[-1].lower()
    tokens = [
        token
        for token in original_name.replace("-", "_").split("_")
        if len(token) >= 4 and token not in {"order"}
    ]
    return next(
        (
            target
            for target in read_targets
            if any(token in target.tool_name.lower() for token in tokens)
        ),
        None,
    )


def _select_compensation_tool(
    *,
    targets: list[Any],
    original_tool_id: str,
    requested_tool_id: str | None,
) -> Any | None:
    write_targets = [target for target in targets if target.is_write]
    if requested_tool_id:
        return next(
            (
                target
                for target in write_targets
                if target.tool_id == requested_tool_id
            ),
            None,
        )
    return next(
        (
            target
            for target in write_targets
            if "reverse" in target.tool_name.lower()
            or "compensat" in target.tool_name.lower()
        ),
        None,
    )


def _arguments_for_tool(
    schema: dict[str, object],
    source: dict[str, object],
) -> dict[str, object]:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return {}
    return {
        str(key): value
        for key, value in source.items()
        if str(key) in properties
    }


def _invalid_state(incident: McpActionIncident) -> ApiProblem:
    return ApiProblem(
        status_code=409,
        code="MCP_INCIDENT_NOT_ACTIONABLE",
        title="MCP incident cannot be updated",
        detail=f"The incident is already {incident.status}.",
    )

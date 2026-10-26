from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from sqlalchemy import select
from sqlalchemy.orm import Session

from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.mcp_connectors.models import (
    DigitalEmployeeMcpBinding,
    McpConnector,
)
from ticket_agent.mcp_connectors.service import McpConnectorService
from ticket_agent.model_gateway.types import AgentToolSpec
from ticket_agent.shared.redaction import redact_sensitive_text
from ticket_agent.tickets.drafts import DraftEvidence
from ticket_agent.tickets.models import Ticket
from ticket_agent.tools.execution import ToolExecutionService
from ticket_agent.tools.registry import ToolDefinition

RemoteCaller = Callable[
    [McpConnector, str, dict[str, object]],
    Awaitable[dict[str, Any]],
]


class McpRemoteToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class McpToolTarget:
    connector_id: UUID
    connector_code: str
    connector_name: str
    tool_name: str
    description: str
    input_schema: dict[str, object]
    is_write: bool
    timeout_seconds: float
    write_approved: bool

    @property
    def tool_id(self) -> str:
        return f"{self.connector_code}.{self.tool_name}"

    @property
    def audit_key(self) -> str:
        return f"mcp:{self.connector_code}:{self.tool_name}"[:100]

    @property
    def spec(self) -> AgentToolSpec:
        return AgentToolSpec(
            tool_id=self.tool_id,
            name=f"{self.connector_name} · {self.tool_name}",
            description=self.description,
            input_schema=self.input_schema,
            is_write=self.is_write,
        )


@dataclass(frozen=True)
class McpExecutionResult:
    tool_id: str
    connector_code: str
    tool_name: str
    status: str
    text: str
    error_code: str | None
    error_message: str | None
    is_write: bool
    duration_ms: int
    tool_call_id: UUID
    approval_id: UUID | None = None
    approval_required_role: str | None = None

    @property
    def evidence(self) -> DraftEvidence | None:
        if self.status != "SUCCEEDED" or not self.text:
            return None
        return DraftEvidence(
            chunk_id=f"mcp:{self.tool_call_id}",
            title=f"MCP · {self.connector_code} · {self.tool_name}",
            version="live",
            content=self.text,
            citation={
                "chunk_id": f"mcp:{self.tool_call_id}",
                "document_id": str(self.tool_call_id),
                "space_id": None,
                "title": f"MCP · {self.connector_code} · {self.tool_name}",
                "version": "live",
                "source_type": "mcp",
            },
        )


class McpToolRuntime:
    def __init__(
        self,
        session: Session,
        *,
        remote_caller: RemoteCaller | None = None,
    ) -> None:
        self.session = session
        self.tool_execution = ToolExecutionService(session)
        self.remote_caller = remote_caller or self._call_remote

    def available_tools(
        self,
        employee: DigitalEmployee,
    ) -> list[McpToolTarget]:
        rows = self.session.execute(
            select(DigitalEmployeeMcpBinding, McpConnector)
            .join(
                McpConnector,
                McpConnector.id == DigitalEmployeeMcpBinding.connector_id,
            )
            .where(
                DigitalEmployeeMcpBinding.employee_id == employee.id,
                DigitalEmployeeMcpBinding.enabled.is_(True),
                McpConnector.status == "ACTIVE",
            )
            .order_by(McpConnector.name)
        ).all()
        targets: list[McpToolTarget] = []
        seen_ids: set[str] = set()
        for binding, connector in rows:
            allowed = set(binding.allowed_tools_json)
            for raw in connector.tools_json:
                name = raw.get("name")
                if not isinstance(name, str) or name not in allowed:
                    continue
                schema = raw.get("input_schema")
                target = McpToolTarget(
                    connector_id=connector.id,
                    connector_code=connector.code,
                    connector_name=connector.name,
                    tool_name=name,
                    description=str(raw.get("description") or ""),
                    input_schema=schema if isinstance(schema, dict) else {},
                    is_write=bool(raw.get("is_write", False)),
                    timeout_seconds=connector.timeout_seconds,
                    write_approved=binding.write_approved,
                )
                if target.tool_id in seen_ids:
                    continue
                seen_ids.add(target.tool_id)
                targets.append(target)
        return targets

    def execute(
        self,
        *,
        employee: DigitalEmployee,
        tool_id: str,
        arguments: dict[str, object],
        correlation_id: str,
        ticket_id: UUID | None,
        requested_by: str | None = None,
        conversation_id: UUID | None = None,
        reason: str = "",
        approved_by: str | None = None,
        approval_id: UUID | None = None,
    ) -> McpExecutionResult:
        if employee.status != "ACTIVE":
            raise ValueError(
                f"Digital employee {employee.id} is not active "
                f"(status={employee.status})"
            )
        target = next(
            (
                item
                for item in self.available_tools(employee)
                if item.tool_id == tool_id
            ),
            None,
        )
        if target is None:
            raise ValueError(f"MCP tool '{tool_id}' is not bound to this employee")
        definition = ToolDefinition(
            key=target.audit_key,
            name=target.spec.name,
            risk_level="R2" if target.is_write else "R0",
            action_type="EXTERNAL_WRITE" if target.is_write else "READ",
            requires_human_approval=target.is_write,
        )
        call = self.tool_execution.begin_external(
            employee=employee,
            definition=definition,
            payload={
                "connector_id": str(target.connector_id),
                "tool_id": target.tool_id,
                "arguments": arguments,
            },
            correlation_id=correlation_id,
            ticket_id=ticket_id,
        )
        started = time.monotonic()
        argument_error = _validate_arguments(
            target.input_schema,
            arguments,
        )
        if argument_error is not None:
            self.tool_execution.fail(
                call,
                error_code="MCP_TOOL_ARGUMENTS_INVALID",
                error_message=argument_error,
            )
            self.session.commit()
            return McpExecutionResult(
                tool_id=target.tool_id,
                connector_code=target.connector_code,
                tool_name=target.tool_name,
                status="FAILED",
                text="",
                error_code=call.error_code,
                error_message=call.error_message,
                is_write=target.is_write,
                duration_ms=_duration_ms(started),
                tool_call_id=call.id,
                approval_id=approval_id,
            )
        action_policy = None
        if target.is_write:
            from ticket_agent.mcp_connectors.policy import (
                evaluate_write_action,
            )

            action_policy = evaluate_write_action(
                target=target,
                arguments=arguments,
                ticket=(
                    self.session.get(Ticket, ticket_id)
                    if ticket_id is not None
                    else None
                ),
            )
            if not action_policy.allowed:
                self.tool_execution.fail(
                    call,
                    error_code=action_policy.reason_code,
                    error_message=action_policy.reason,
                )
                call.action_type = "EXTERNAL_WRITE"
                self.session.commit()
                return McpExecutionResult(
                    tool_id=target.tool_id,
                    connector_code=target.connector_code,
                    tool_name=target.tool_name,
                    status="FAILED",
                    text="",
                    error_code=call.error_code,
                    error_message=call.error_message,
                    is_write=True,
                    duration_ms=_duration_ms(started),
                    tool_call_id=call.id,
                    approval_id=approval_id,
                    approval_required_role=action_policy.required_role,
                )
        approved_execution = (
            target.is_write
            and target.write_approved
            and approved_by is not None
            and approval_id is not None
            and approved_by != requested_by
        )
        if target.is_write and not approved_execution:
            call.status = "DENIED"
            call.completed_at = datetime.now(UTC)
            if not target.write_approved:
                call.error_code = "MCP_WRITE_PERMISSION_NOT_GRANTED"
                call.error_message = (
                    "Write permission is not granted for this employee binding."
                )
                self.session.commit()
            elif requested_by is None:
                call.error_code = "MCP_APPROVAL_REQUESTER_REQUIRED"
                call.error_message = (
                    "A request actor is required to open write approval."
                )
                self.session.commit()
            else:
                from ticket_agent.mcp_connectors.approvals import (
                    McpToolApprovalService,
                )

                assert action_policy is not None
                approval, reused = McpToolApprovalService(
                    self.session
                ).request(
                    business_unit_id=employee.business_unit_id,
                    employee_id=employee.id,
                    connector_id=target.connector_id,
                    connector_code=target.connector_code,
                    tool_name=target.tool_name,
                    tool_id=target.tool_id,
                    arguments=arguments,
                    requested_by=requested_by,
                    correlation_id=correlation_id,
                    ticket_id=ticket_id,
                    conversation_id=conversation_id,
                    reason=reason,
                    request_tool_call_id=call.id,
                    required_role=action_policy.required_role,
                    policy=action_policy.snapshot,
                )
                call.error_code = "MCP_WRITE_REQUIRES_APPROVAL"
                call.error_message = (
                    "Independent human approval is required before execution."
                )
                self.session.commit()
                if approval.status == "SUCCEEDED":
                    approval_result = approval.result_json
                    result_text = str(approval_result.get("text") or "")
                    return McpExecutionResult(
                        tool_id=target.tool_id,
                        connector_code=target.connector_code,
                        tool_name=target.tool_name,
                        status="SUCCEEDED",
                        text=result_text,
                        error_code=None,
                        error_message=None,
                        is_write=True,
                        duration_ms=0,
                        tool_call_id=(
                            approval.execution_tool_call_id or call.id
                        ),
                        approval_id=approval.id,
                        approval_required_role=approval.required_role,
                    )
                if approval.status == "EXECUTING":
                    call.error_code = "MCP_APPROVAL_IN_PROGRESS"
                elif approval.status == "FAILED":
                    call.error_code = "MCP_APPROVAL_EXECUTION_FAILED"
                return McpExecutionResult(
                    tool_id=target.tool_id,
                    connector_code=target.connector_code,
                    tool_name=target.tool_name,
                    status="APPROVAL_REQUIRED",
                    text="",
                    error_code=call.error_code,
                    error_message=(
                        call.error_message
                        if not reused
                        else f"Existing approval is {approval.status}."
                    ),
                    is_write=True,
                    duration_ms=_duration_ms(started),
                    tool_call_id=call.id,
                    approval_id=approval.id,
                    approval_required_role=approval.required_role,
                )
            return McpExecutionResult(
                tool_id=target.tool_id,
                connector_code=target.connector_code,
                tool_name=target.tool_name,
                status="APPROVAL_REQUIRED",
                text="",
                error_code=call.error_code,
                error_message=call.error_message,
                is_write=True,
                duration_ms=_duration_ms(started),
                tool_call_id=call.id,
                approval_id=approval_id,
            )

        try:
            connector = self.session.get(McpConnector, target.connector_id)
            if connector is None:
                raise ValueError("MCP connector no longer exists")
            result = _run_sync(
                self.remote_caller(connector, target.tool_name, arguments)
            )
            is_error = bool(result.get("is_error", False))
            result_text = _result_text(result)
            if is_error:
                raise McpRemoteToolError(
                    result_text or "MCP tool returned an error"
                )
            self.tool_execution.succeed(
                call,
                {
                    "connector_code": target.connector_code,
                    "tool_name": target.tool_name,
                    "result_length": len(result_text),
                    "result_preview": result_text[:1000],
                },
            )
            self.session.commit()
            return McpExecutionResult(
                tool_id=target.tool_id,
                connector_code=target.connector_code,
                tool_name=target.tool_name,
                status="SUCCEEDED",
                text=result_text,
                error_code=None,
                error_message=None,
                is_write=target.is_write,
                duration_ms=_duration_ms(started),
                tool_call_id=call.id,
                approval_id=approval_id,
            )
        except Exception as exc:
            error_code = (
                "MCP_TOOL_REJECTED"
                if isinstance(exc, McpRemoteToolError)
                else "MCP_TOOL_CALL_FAILED"
            )
            self.tool_execution.fail(
                call,
                error_code=error_code,
                error_message=f"{type(exc).__name__}: {exc}",
            )
            self.session.commit()
            return McpExecutionResult(
                tool_id=target.tool_id,
                connector_code=target.connector_code,
                tool_name=target.tool_name,
                status="FAILED",
                text="",
                error_code=call.error_code,
                error_message=call.error_message,
                is_write=target.is_write,
                duration_ms=_duration_ms(started),
                tool_call_id=call.id,
                approval_id=approval_id,
            )

    async def _call_remote(
        self,
        connector: McpConnector,
        tool_name: str,
        arguments: dict[str, object],
    ) -> dict[str, Any]:
        headers = McpConnectorService._resolve_headers(connector.header_env_json)
        async with (
            streamablehttp_client(
                connector.url,
                headers=headers,
                timeout=connector.timeout_seconds,
                sse_read_timeout=connector.timeout_seconds,
            ) as (read_stream, write_stream, _session_id),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            result = await asyncio.wait_for(
                session.call_tool(tool_name, arguments=arguments),
                timeout=connector.timeout_seconds,
            )
        content: list[Any] = []
        for item in result.content:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                content.append(text)
            elif hasattr(item, "model_dump"):
                content.append(item.model_dump(mode="json"))
            else:
                content.append(str(item))
        return {
            "is_error": result.isError,
            "structured_content": result.structuredContent,
            "content": content,
        }


def _result_text(result: dict[str, Any]) -> str:
    structured = result.get("structured_content")
    content = result.get("content", [])
    parts: list[str] = []
    if structured not in (None, {}, []):
        parts.append(json.dumps(structured, ensure_ascii=False, indent=2))
    if isinstance(content, list):
        parts.extend(str(item) for item in content)
    return redact_sensitive_text("\n".join(parts))[:20_000]


def _run_sync(awaitable: Awaitable[dict[str, Any]]) -> dict[str, Any]:
    async def run() -> dict[str, Any]:
        return await awaitable

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run())
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, run()).result()


def _duration_ms(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1000))


def _validate_arguments(
    schema: dict[str, object],
    arguments: dict[str, object],
) -> str | None:
    required = schema.get("required")
    if isinstance(required, list):
        missing = [
            str(name)
            for name in required
            if isinstance(name, str) and name not in arguments
        ]
        if missing:
            return f"Missing required MCP arguments: {', '.join(missing)}"
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return None
    expected_types: dict[str, type[Any] | tuple[type[Any], ...]] = {
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    for name, raw_rule in properties.items():
        if name not in arguments or not isinstance(raw_rule, dict):
            continue
        type_name = raw_rule.get("type")
        expected = expected_types.get(type_name) if isinstance(type_name, str) else None
        if expected is not None and not isinstance(arguments[name], expected):
            return f"MCP argument '{name}' must be {type_name}"
        enum = raw_rule.get("enum")
        if isinstance(enum, list) and arguments[name] not in enum:
            return f"MCP argument '{name}' must be one of the declared values"
    return None



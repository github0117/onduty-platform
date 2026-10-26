from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ticket_agent.digital_employees.service import DigitalEmployeeService
from ticket_agent.mcp_connectors.models import (
    DigitalEmployeeMcpBinding,
    McpConnector,
)
from ticket_agent.mcp_connectors.schemas import (
    EmployeeMcpBindingView,
    McpConnectorCreate,
    McpConnectorUpdate,
    McpConnectorView,
    McpHealthView,
    McpToolView,
)
from ticket_agent.shared.errors import ApiProblem

WRITE_TOOL_PREFIXES = (
    "create",
    "update",
    "change",
    "modify",
    "delete",
    "write",
    "publish",
    "refund",
    "cancel",
    "send",
    "reverse",
    "compensate",
)


class McpConnectorService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_connectors(self, business_unit_id: str) -> list[McpConnector]:
        return list(
            self.session.scalars(
                select(McpConnector)
                .where(McpConnector.business_unit_id == business_unit_id)
                .order_by(McpConnector.name)
            ).all()
        )

    def get(self, connector_id: UUID) -> McpConnector:
        connector = self.session.get(McpConnector, connector_id)
        if connector is None:
            raise ApiProblem(
                status_code=404,
                code="MCP_CONNECTOR_NOT_FOUND",
                title="MCP connector not found",
                detail=f"MCP connector {connector_id} does not exist.",
            )
        return connector

    def create(
        self,
        payload: McpConnectorCreate,
        *,
        actor_id: str,
    ) -> McpConnector:
        existing = self.session.scalar(
            select(McpConnector).where(
                McpConnector.business_unit_id == payload.business_unit_id,
                McpConnector.code == payload.code,
            )
        )
        if existing is not None:
            raise ApiProblem(
                status_code=409,
                code="MCP_CONNECTOR_EXISTS",
                title="MCP connector already exists",
                detail="Connector code must be unique within the business unit.",
            )
        connector = McpConnector(
            business_unit_id=payload.business_unit_id,
            code=payload.code,
            name=payload.name,
            description=payload.description,
            transport=payload.transport,
            url=str(payload.url),
            header_env_json=payload.header_env,
            timeout_seconds=payload.timeout_seconds,
            status=payload.status,
            created_by=actor_id,
        )
        self.session.add(connector)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ApiProblem(
                status_code=409,
                code="MCP_CONNECTOR_EXISTS",
                title="MCP connector already exists",
                detail=(
                    "Connector code must be unique within the business unit."
                ),
            ) from exc
        self.session.refresh(connector)
        return connector

    def update(
        self,
        connector_id: UUID,
        payload: McpConnectorUpdate,
        *,
        actor_id: str,
    ) -> McpConnector:
        connector = self.get(connector_id)
        for field, column in (
            ("name", "name"),
            ("description", "description"),
            ("timeout_seconds", "timeout_seconds"),
            ("status", "status"),
        ):
            value = getattr(payload, field)
            if value is not None:
                setattr(connector, column, value)
        if payload.url is not None:
            connector.url = str(payload.url)
        if payload.header_env is not None:
            connector.header_env_json = payload.header_env
        connector.last_check_error = None
        connector.tools_json = []
        self.session.flush()
        self._invalidate_bound_employees(
            connector,
            actor_id=actor_id,
            note=(
                f"MCP connector {connector.code} changed; "
                "employee reactivation required"
            ),
                require_baseline=True,
        )
        self.session.commit()
        self.session.refresh(connector)
        return connector

    async def discover(
        self,
        connector_id: UUID,
        *,
        actor_id: str,
    ) -> McpHealthView:
        connector = self.get(connector_id)
        checked_at = datetime.now(UTC)
        try:
            headers = self._resolve_headers(connector.header_env_json)
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
                result = await session.list_tools()
            tools = [self._tool_view(tool) for tool in result.tools]
            connector.tools_json = [tool.model_dump(mode="json") for tool in tools]
            connector.last_checked_at = checked_at
            connector.last_check_error = None
            self.session.flush()
            self._invalidate_bound_employees(
                connector,
                actor_id=actor_id,
                note=(
                    f"MCP connector {connector.code} tools changed; "
                    "employee reactivation required"
                ),
                require_baseline=True,
            )
            self.session.commit()
            return McpHealthView(
                connector_id=connector.id,
                healthy=True,
                tool_count=len(tools),
                tools=tools,
                error=None,
                checked_at=checked_at,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:2000]
            connector.last_checked_at = checked_at
            connector.last_check_error = error
            connector.tools_json = []
            self.session.flush()
            self._invalidate_bound_employees(
                connector,
                actor_id=actor_id,
                note=(
                    f"MCP connector {connector.code} health check failed; "
                    "employee reactivation required"
                ),
                require_baseline=True,
            )
            self.session.commit()
            return McpHealthView(
                connector_id=connector.id,
                healthy=False,
                tool_count=0,
                tools=[],
                error=error,
                checked_at=checked_at,
            )

    def list_employee_bindings(
        self,
        employee_id: UUID,
    ) -> list[EmployeeMcpBindingView]:
        DigitalEmployeeService(self.session).get(employee_id)
        rows = self.session.execute(
            select(DigitalEmployeeMcpBinding, McpConnector)
            .join(
                McpConnector,
                McpConnector.id == DigitalEmployeeMcpBinding.connector_id,
            )
            .where(DigitalEmployeeMcpBinding.employee_id == employee_id)
            .order_by(McpConnector.name)
        ).all()
        return [
            self.binding_view(binding, connector)
            for binding, connector in rows
        ]

    def replace_employee_bindings(
        self,
        employee_id: UUID,
        bindings: list[dict[str, Any]],
        *,
        commit: bool = True,
        actor_id: str = "system.mcp_binding",
    ) -> list[EmployeeMcpBindingView]:
        employee_service = DigitalEmployeeService(self.session)
        employee = employee_service.get_for_update(employee_id)
        connector_ids = [
            binding["connector_id"]
            for binding in bindings
            if isinstance(binding.get("connector_id"), UUID)
        ]
        if len(connector_ids) != len(bindings):
            raise ApiProblem(
                status_code=422,
                code="MCP_BINDING_INVALID",
                title="Invalid MCP binding",
                detail="Every binding must include a valid connector_id.",
            )
        if len(connector_ids) != len(set(connector_ids)):
            raise ApiProblem(
                status_code=422,
                code="MCP_BINDING_DUPLICATED",
                title="Duplicate MCP binding",
                detail="Each connector can appear only once.",
            )
        connectors = list(
            self.session.scalars(
                select(McpConnector).where(McpConnector.id.in_(connector_ids))
            ).all()
        )
        if len(connectors) != len(set(connector_ids)):
            raise ApiProblem(
                status_code=422,
                code="MCP_CONNECTOR_NOT_FOUND",
                title="MCP connector not found",
                detail="One or more connector IDs do not exist.",
            )
        if any(
            connector.business_unit_id != employee.business_unit_id
            for connector in connectors
        ):
            raise ApiProblem(
                status_code=422,
                code="MCP_CONNECTOR_UNIT_MISMATCH",
                title="MCP connector belongs to another business unit",
                detail="Employee and connector must belong to the same unit.",
            )
        self.session.execute(
            delete(DigitalEmployeeMcpBinding).where(
                DigitalEmployeeMcpBinding.employee_id == employee_id
            )
        )
        connector_by_id = {connector.id: connector for connector in connectors}
        created: list[tuple[DigitalEmployeeMcpBinding, McpConnector]] = []
        for raw in bindings:
            connector_id = raw["connector_id"]
            if not isinstance(connector_id, UUID):
                continue
            allowed_tools = raw.get("allowed_tools", [])
            binding = DigitalEmployeeMcpBinding(
                employee_id=employee_id,
                connector_id=connector_id,
                enabled=bool(raw.get("enabled", True)),
                allowed_tools_json=[
                    str(tool)
                    for tool in allowed_tools
                    if isinstance(tool, str)
                ]
                if isinstance(allowed_tools, list)
                else [],
                write_approved=bool(raw.get("write_approved", False)),
            )
            self.session.add(binding)
            created.append((binding, connector_by_id[connector_id]))
        self.session.flush()
        if commit:
            employee_service.invalidate_activation_if_changed(
                employee,
                actor_id=actor_id,
                note="Employee MCP bindings changed; reactivation required",
            )
            self.session.commit()
        return [
            self.binding_view(binding, connector)
            for binding, connector in created
        ]

    @staticmethod
    def view(connector: McpConnector) -> McpConnectorView:
        return McpConnectorView(
            id=connector.id,
            business_unit_id=connector.business_unit_id,
            code=connector.code,
            name=connector.name,
            description=connector.description,
            transport=connector.transport,
            url=connector.url,
            header_env=connector.header_env_json,
            timeout_seconds=connector.timeout_seconds,
            status=connector.status,
            tools=[
                McpToolView.model_validate(tool)
                for tool in connector.tools_json
            ],
            last_checked_at=connector.last_checked_at,
            last_check_error=connector.last_check_error,
            created_at=connector.created_at,
            updated_at=connector.updated_at,
        )

    @staticmethod
    def binding_view(
        binding: DigitalEmployeeMcpBinding,
        connector: McpConnector,
    ) -> EmployeeMcpBindingView:
        return EmployeeMcpBindingView(
            id=binding.id,
            employee_id=binding.employee_id,
            connector_id=binding.connector_id,
            connector_code=connector.code,
            connector_name=connector.name,
            enabled=binding.enabled,
            allowed_tools=binding.allowed_tools_json,
            write_approved=binding.write_approved,
        )

    @staticmethod
    def _resolve_headers(header_env: dict[str, str]) -> dict[str, str]:
        headers: dict[str, str] = {}
        for header, env_name in header_env.items():
            value = os.environ.get(env_name)
            if not value:
                raise ValueError(f"Environment variable {env_name} is not set")
            headers[str(header)] = value
        return headers

    def _invalidate_bound_employees(
        self,
        connector: McpConnector,
        *,
        actor_id: str,
        note: str,
        require_baseline: bool = False,
    ) -> None:
        employee_ids = set(
            self.session.scalars(
                select(DigitalEmployeeMcpBinding.employee_id).where(
                    DigitalEmployeeMcpBinding.connector_id
                    == connector.id,
                    DigitalEmployeeMcpBinding.enabled.is_(True),
                )
            ).all()
        )
        employee_service = DigitalEmployeeService(self.session)
        for employee_id in employee_ids:
            employee_service.invalidate_activation_if_changed(
                employee_service.get_for_update(employee_id),
                actor_id=actor_id,
                note=note,
                require_baseline=require_baseline,
            )

    @staticmethod
    def _tool_view(tool: object) -> McpToolView:
        name = str(getattr(tool, "name", "unnamed"))
        description = str(getattr(tool, "description", "") or "")
        schema = getattr(tool, "inputSchema", None)
        if not isinstance(schema, dict):
            schema = getattr(tool, "input_schema", {})
        annotations = getattr(tool, "annotations", None)
        read_only = getattr(annotations, "readOnlyHint", None)
        is_write = (
            name.lower().startswith(WRITE_TOOL_PREFIXES)
            or read_only is False
        )
        return McpToolView(
            name=name,
            description=description,
            input_schema=schema if isinstance(schema, dict) else {},
            is_write=is_write,
        )

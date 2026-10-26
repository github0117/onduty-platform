from dataclasses import dataclass

from ticket_agent.digital_employees.models import DigitalEmployee


class ToolPermissionError(RuntimeError):
    def __init__(self, message: str, *, tool_key: str) -> None:
        super().__init__(message)
        self.code = "TOOL_PERMISSION_DENIED"
        self.tool_key = tool_key


@dataclass(frozen=True)
class ToolDefinition:
    key: str
    name: str
    risk_level: str
    action_type: str
    requires_human_approval: bool = False


class ToolRegistry:
    _tools = {
        "ticket.read": ToolDefinition(
            key="ticket.read",
            name="读取工单上下文",
            risk_level="R0",
            action_type="READ",
        ),
        "knowledge.search": ToolDefinition(
            key="knowledge.search",
            name="检索私有知识",
            risk_level="R0",
            action_type="READ",
        ),
        "draft.create": ToolDefinition(
            key="draft.create",
            name="生成内部草稿",
            risk_level="R1",
            action_type="INTERNAL_WRITE",
        ),
        "ticket.sync": ToolDefinition(
            key="ticket.sync",
            name="回写外部工单",
            risk_level="R2",
            action_type="EXTERNAL_WRITE",
            requires_human_approval=True,
        ),
        "employee_profile.read": ToolDefinition(
            key="employee_profile.read",
            name="读取员工资料",
            risk_level="R1",
            action_type="READ",
        ),
    }

    def authorize(
        self,
        employee: DigitalEmployee,
        tool_key: str,
        *,
        human_approved: bool = False,
        policy_approved: bool = False,
    ) -> ToolDefinition:
        definition = self._tools.get(tool_key)
        if definition is None:
            raise ToolPermissionError(
                f"Tool '{tool_key}' is not registered.",
                tool_key=tool_key,
            )
        if tool_key not in employee.tool_allowlist_json:
            raise ToolPermissionError(
                f"Digital employee '{employee.employee_key}' cannot use '{tool_key}'.",
                tool_key=tool_key,
            )
        if (
            definition.requires_human_approval
            and not human_approved
            and not policy_approved
        ):
            raise ToolPermissionError(
                f"Tool '{tool_key}' requires human approval.",
                tool_key=tool_key,
            )
        return definition

    def authorize_all(
        self,
        employee: DigitalEmployee,
        tool_keys: set[str],
    ) -> None:
        for tool_key in sorted(tool_keys):
            self.authorize(employee, tool_key)

    def definition(self, tool_key: str) -> ToolDefinition:
        definition = self._tools.get(tool_key)
        if definition is None:
            raise ToolPermissionError(
                f"Tool '{tool_key}' is not registered.",
                tool_key=tool_key,
            )
        return definition


tool_registry = ToolRegistry()


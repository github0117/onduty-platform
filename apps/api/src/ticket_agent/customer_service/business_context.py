from __future__ import annotations

import hashlib
import re
from typing import Any

import httpx

from ticket_agent.customer_service.models import (
    CustomerConversation,
    CustomerMessage,
)
from ticket_agent.customer_service.schemas import (
    AddressChangeCreate,
    BusinessCustomerView,
    BusinessOrderView,
    BusinessResolutionView,
    CustomerBusinessActionView,
    CustomerBusinessContextView,
)
from ticket_agent.digital_employees.service import DigitalEmployeeService
from ticket_agent.mcp_connectors.runtime import McpToolRuntime
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import Settings, get_settings
from ticket_agent.tickets.models import Ticket

ORDER_REFERENCE_PATTERN = re.compile(
    r"\b(?:MOCK-)?ORD-[A-Z0-9][A-Z0-9-]{2,}\b",
    re.IGNORECASE,
)


class CustomerBusinessContextService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()

    def resolve(
        self,
        conversation: CustomerConversation,
        messages: list[CustomerMessage],
        *,
        order_id: str | None = None,
    ) -> CustomerBusinessContextView:
        resolved_order_id = order_id or self.extract_order_id(messages)
        self._ensure_configured()
        params = (
            {"order_id": resolved_order_id}
            if resolved_order_id
            else None
        )
        try:
            response = httpx.get(
                (
                    f"{self.settings.business_sandbox_base_url.rstrip('/')}"
                    f"/customers/{conversation.requester_ref}"
                    "/business-context"
                ),
                params=params,
                timeout=self.settings.business_sandbox_timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise ApiProblem(
                    status_code=404,
                    code="BUSINESS_CONTEXT_NOT_FOUND",
                    title="未找到客户和订单",
                    detail=(
                        "当前会话没有可识别的客户或订单，"
                        "请让客户补充订单号或转人工核对。"
                    ),
                ) from exc
            raise ApiProblem(
                status_code=502,
                code="BUSINESS_CONTEXT_UNAVAILABLE",
                title="业务上下文读取失败",
                detail=(
                    "客户、订单或售后沙箱暂时不可用，请稍后重试或转人工处理。"
                ),
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ApiProblem(
                status_code=502,
                code="BUSINESS_CONTEXT_UNAVAILABLE",
                title="业务上下文读取失败",
                detail=(
                    "客户、订单或售后沙箱暂时不可用，请稍后重试或转人工处理。"
                ),
            ) from exc
        if not isinstance(body, dict):
            raise ApiProblem(
                status_code=502,
                code="BUSINESS_CONTEXT_INVALID",
                title="业务上下文格式错误",
                detail="业务沙箱返回的数据不是有效对象。",
            )
        customer = body.get("customer")
        order = body.get("order")
        resolution = body.get("resolution")
        if not all(
            isinstance(item, dict)
            for item in (customer, order, resolution)
        ):
            raise ApiProblem(
                status_code=502,
                code="BUSINESS_CONTEXT_INVALID",
                title="业务上下文格式错误",
                detail="业务沙箱缺少客户、订单或匹配说明。",
            )
        assert isinstance(customer, dict)
        assert isinstance(order, dict)
        assert isinstance(resolution, dict)
        address = order.get("shipping_address")
        if isinstance(address, dict):
            address = dict(address)
            address["phone"] = _mask_phone(str(address.get("phone") or ""))
        try:
            order_view = BusinessOrderView.model_validate(
                {**order, "shipping_address": address}
            )
            customer_view = BusinessCustomerView.model_validate(customer)
            resolution_view = BusinessResolutionView.model_validate(resolution)
        except ValueError as exc:
            raise ApiProblem(
                status_code=502,
                code="BUSINESS_CONTEXT_INVALID",
                title="业务上下文格式错误",
                detail="业务沙箱返回的客户或订单字段不完整。",
            ) from exc
        return CustomerBusinessContextView(
            customer_ref=conversation.requester_ref,
            customer=customer_view,
            order=order_view,
            resolution=resolution_view,
            source=str(body.get("source") or "business-sandbox"),
        )

    @staticmethod
    def extract_order_id(messages: list[CustomerMessage]) -> str | None:
        for message in reversed(messages):
            match = ORDER_REFERENCE_PATTERN.search(message.content)
            if match:
                return match.group(0).upper()
        return None

    def _ensure_configured(self) -> None:
        if (
            self.settings.business_sandbox_provider == "none"
            or not self.settings.business_sandbox_base_url
        ):
            raise ApiProblem(
                status_code=503,
                code="BUSINESS_SANDBOX_NOT_CONFIGURED",
                title="业务沙箱未配置",
                detail=(
                    "当前未连接客户、订单或售后沙箱，不能展示业务上下文。"
                ),
            )


class CustomerBusinessActionService:
    def __init__(self, session: Any) -> None:
        self.session = session

    def request_address_change(
        self,
        conversation: CustomerConversation,
        messages: list[CustomerMessage],
        payload: AddressChangeCreate,
        *,
        actor_id: str,
        correlation_id: str,
    ) -> CustomerBusinessActionView:
        if conversation.assigned_agent_id != actor_id:
            raise ApiProblem(
                status_code=409,
                code="CONVERSATION_NOT_ASSIGNED_TO_ACTOR",
                title="请先接管会话",
                detail="只有当前会话负责人可以发起收货地址修改。",
            )
        if conversation.employee_id is None or conversation.current_ticket_id is None:
            raise ApiProblem(
                status_code=409,
                code="BUSINESS_ACTION_CONTEXT_MISSING",
                title="缺少数字员工或工单",
                detail="当前会话尚未绑定可执行动作的数字员工和工单。",
            )
        context = CustomerBusinessContextService().resolve(
            conversation,
            messages,
            order_id=payload.order_id,
        )
        if context.order.order_id != payload.order_id:
            raise ApiProblem(
                status_code=409,
                code="BUSINESS_CONTEXT_ORDER_MISMATCH",
                title="订单上下文不一致",
                detail="会话中的订单与本次改址目标不一致，请重新核对。",
            )
        if context.order.order_version != payload.expected_order_version:
            raise ApiProblem(
                status_code=409,
                code="BUSINESS_CONTEXT_ORDER_CHANGED",
                title="订单状态已更新",
                detail="订单版本已变化，请刷新业务上下文后重新提交。",
            )
        ticket = self.session.get(Ticket, conversation.current_ticket_id)
        if ticket is None:
            raise ApiProblem(
                status_code=409,
                code="BUSINESS_ACTION_TICKET_MISSING",
                title="工单不存在",
                detail="当前会话关联工单已不可用，不能发起外部写入。",
            )
        employee = DigitalEmployeeService(self.session).get(
            conversation.employee_id
        )
        runtime = McpToolRuntime(self.session)
        target = next(
            (
                item
                for item in runtime.available_tools(employee)
                if item.tool_name == "change_shipping_address"
            ),
            None,
        )
        if target is None:
            raise ApiProblem(
                status_code=409,
                code="BUSINESS_ACTION_TOOL_NOT_CONFIGURED",
                title="改址工具未启用",
                detail="请先为当前数字员工启用业务沙箱的改址写工具。",
            )
        idempotency_key = _address_change_key(
            conversation_id=str(conversation.id),
            payload=payload,
        )
        result = runtime.execute(
            employee=employee,
            tool_id=target.tool_id,
            arguments={
                "order_id": payload.order_id,
                "recipient": payload.recipient,
                "phone": payload.phone,
                "province": payload.province,
                "city": payload.city,
                "district": payload.district,
                "detail": payload.detail,
                "expected_order_version": payload.expected_order_version,
                "idempotency_key": idempotency_key,
                "reason": payload.reason,
            },
            correlation_id=correlation_id,
            ticket_id=ticket.id,
            requested_by=actor_id,
            conversation_id=conversation.id,
            reason=payload.reason,
        )
        if result.status == "APPROVAL_REQUIRED" and result.approval_id:
            message = (
                "改址申请已提交，等待客服主管独立审批；"
                "审批通过前不会调用外部物流系统。"
            )
        elif result.status == "SUCCEEDED":
            message = "收货地址已修改，并已从业务系统确认结果。"
        else:
            message = result.error_message or "改址申请未执行，请检查配置后重试。"
        return CustomerBusinessActionView(
            conversation_id=conversation.id,
            order_id=payload.order_id,
            action_type="CHANGE_SHIPPING_ADDRESS",
            status=result.status,
            message=message,
            tool_id=result.tool_id,
            tool_call_id=result.tool_call_id,
            approval_id=result.approval_id,
            approval_required_role=result.approval_required_role,
            idempotency_key=idempotency_key,
        )


def _address_change_key(
    *,
    conversation_id: str,
    payload: AddressChangeCreate,
) -> str:
    simulation_marker = {
        "normal": "normal",
        "timeout_unknown": "TIMEOUT",
        "reject": "REJECT",
    }[payload.simulation_mode]
    canonical = "|".join(
        [
            conversation_id,
            payload.order_id,
            payload.expected_order_version.__str__(),
            payload.recipient.strip(),
            payload.phone.strip(),
            payload.province.strip(),
            payload.city.strip(),
            payload.district.strip(),
            payload.detail.strip(),
        ]
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()[:32]
    return f"address-change:{simulation_marker}:{digest}"


def _mask_phone(phone: str) -> str:
    if len(phone) < 7:
        return phone
    return f"{phone[:3]}****{phone[-4:]}"

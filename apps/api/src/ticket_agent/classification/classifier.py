from dataclasses import dataclass

from ticket_agent.classification.conversation_signals import (
    is_technical_documentation_question,
)
from ticket_agent.model_gateway.factory import get_model_gateway
from ticket_agent.model_gateway.local import LocalModelGateway
from ticket_agent.model_gateway.types import (
    GatewayResponse,
    TicketCategory,
    TicketModelGateway,
)
from ticket_agent.shared.settings import get_settings
from ticket_agent.tickets.domain import RiskLevel


@dataclass(frozen=True)
class AnalysisResult:
    category_primary: str
    category_secondary: str
    confidence: float
    risk_level: RiskLevel
    risk_tags: list[str]
    reason_codes: list[str]
    summary: str
    needs_human: bool
    human_reason: str | None
    model_provider: str
    model_name: str
    fallback_used: bool


class MockClassifier:
    """Risk-aware classifier with a replaceable model gateway."""

    _critical_security_keywords = {"数据泄露", "盗用", "账号被盗", "被黑"}
    _security_keywords = {
        "数据泄露",
        "泄露",
        "越权",
        "私有仓库",
        "密钥",
        "访问令牌",
        "系统提示词",
        "盗用",
        "账号被盗",
        "被黑",
        "隐私",
        "删除数据",
        "导出数据",
        "律师函",
        "法务",
        "监管",
    }
    _complaint_keywords = {"投诉", "曝光", "举报"}
    _transaction_keywords = {"退款", "赔付", "重复扣费", "交易争议"}
    _billing_keywords = {"发票", "账单", "扣费"}
    _incident_keywords = {"不可用", "报错", "崩溃", "故障", "超时", "异常"}
    _howto_keywords = {"怎么", "如何", "配置", "设置", "使用", "开通"}
    _access_keywords = {"登录", "密码", "权限", "账号", "帐号"}
    _ecommerce_presales_keywords = {
        "尺码",
        "鞋面",
        "内里",
        "材质",
        "筒高",
        "跟高",
        "库存",
        "发货",
        "颜色",
        "怎么选",
    }
    _ecommerce_aftersales_keywords = {
        "退货",
        "退换",
        "退款",
        "物流",
        "快递",
        "订单",
        "售后",
        "漏发",
        "少发",
        "质量问题",
    }
    _address_change_keywords = {
        "改地址",
        "修改地址",
        "修改收货地址",
        "换地址",
        "更换收货地址",
        "变更地址",
        "变更收货地址",
        "更改收货地址",
        "收货地址改",
    }

    _category_risks: dict[TicketCategory, RiskLevel] = {
        "data_privacy_security": RiskLevel.R2,
        "complaint_escalation": RiskLevel.R2,
        "transaction_dispute": RiskLevel.R2,
        "billing_invoice": RiskLevel.R1,
        "service_incident": RiskLevel.R1,
        "access_identity": RiskLevel.R0,
        "product_howto": RiskLevel.R0,
        "ecommerce_presales": RiskLevel.R0,
        "ecommerce_aftersales": RiskLevel.R1,
        "other_unclassified": RiskLevel.R1,
    }

    def __init__(
        self,
        gateway: TicketModelGateway | None = None,
        *,
        confidence_threshold: float | None = None,
    ) -> None:
        self.gateway = gateway or LocalModelGateway()
        self.name = f"risk-policy+{self.gateway.name}"
        self.confidence_threshold = confidence_threshold

    def classify(
        self,
        *,
        subject: str,
        body: str,
        customer_tier: str,
    ) -> AnalysisResult:
        text = f"{subject}\n{body}".lower()
        gateway_response = self.gateway.classify(subject=subject, body=body)
        category, secondary, risk_level, confidence, reason_codes, risk_tags = (
            self._apply_hard_rules(text, gateway_response)
        )

        if customer_tier.lower() == "enterprise":
            reason_codes.append("CUSTOMER_ENTERPRISE")
        if gateway_response.fallback_used:
            reason_codes.append("MODEL_FALLBACK_LOCAL")

        threshold = (
            self.confidence_threshold
            if self.confidence_threshold is not None
            else get_settings().classification_confidence_threshold
        )
        needs_human = (
            risk_level in {RiskLevel.R2, RiskLevel.R3}
            or confidence < threshold
            or category == "other_unclassified"
        )
        human_reason = None
        if risk_level in {RiskLevel.R2, RiskLevel.R3}:
            human_reason = "HIGH_RISK_TOPIC"
        elif confidence < threshold:
            human_reason = "LOW_CLASSIFICATION_CONFIDENCE"
        elif category == "other_unclassified":
            human_reason = "UNCLASSIFIED"

        return AnalysisResult(
            category_primary=category,
            category_secondary=secondary,
            confidence=confidence,
            risk_level=risk_level,
            risk_tags=list(dict.fromkeys(risk_tags)),
            reason_codes=list(dict.fromkeys(reason_codes)),
            summary=gateway_response.classification.summary,
            needs_human=needs_human,
            human_reason=human_reason,
            model_provider=gateway_response.provider,
            model_name=gateway_response.model,
            fallback_used=gateway_response.fallback_used,
        )

    def _apply_hard_rules(
        self,
        text: str,
        response: GatewayResponse,
    ) -> tuple[TicketCategory, str, RiskLevel, float, list[str], list[str]]:
        model = response.classification
        category: TicketCategory = model.primary
        secondary = model.secondary
        confidence = model.confidence
        risk_level = self._category_risks[category]
        reason_codes: list[str] = []
        risk_tags = list(model.risk_tags)

        if self._contains(text, self._critical_security_keywords):
            category, secondary = "data_privacy_security", "data_leak"
            risk_level = RiskLevel.R3
            confidence = max(confidence, 0.96)
            risk_tags.extend(["DATA_LEAK", "CRITICAL_SECURITY"])
            reason_codes.append("SECURITY_HARD_RULE")
        elif self._contains(text, self._security_keywords):
            category, secondary = "data_privacy_security", "security_request"
            risk_level = RiskLevel.R2
            confidence = max(confidence, 0.92)
            risk_tags.append("SECURITY_PRIVACY")
            reason_codes.append("SECURITY_HARD_RULE")
        elif self._contains(text, self._complaint_keywords):
            category, secondary = "complaint_escalation", "service_complaint"
            risk_level = RiskLevel.R2
            confidence = max(confidence, 0.91)
            risk_tags.append("COMPLAINT")
            reason_codes.append("COMPLAINT_HARD_RULE")
        elif self._contains(text, self._address_change_keywords):
            category, secondary = "ecommerce_aftersales", "address_change"
            risk_level = RiskLevel.R2
            confidence = max(confidence, 0.98)
            risk_tags.extend(["ADDRESS_CHANGE", "EXTERNAL_WRITE"])
            reason_codes.append("ADDRESS_CHANGE_HARD_RULE")
        elif (
            any(term in text for term in ("雪地靴", "商品"))
            and self._contains(text, self._ecommerce_aftersales_keywords)
        ):
            category, secondary = "ecommerce_aftersales", "order_after_sales"
            risk_level = RiskLevel.R1
            confidence = max(confidence, 0.93)
            risk_tags.append("ORDER_ACTION")
            reason_codes.append("ECOMMERCE_AFTERSALES_RULE")
        elif is_technical_documentation_question(text):
            category, secondary = "product_howto", "technical_documentation"
            risk_level = RiskLevel.R0
            confidence = max(confidence, 0.94)
            reason_codes.append("TECHNICAL_DOCUMENTATION_RULE")
        elif self._contains(text, self._ecommerce_presales_keywords):
            category, secondary = "ecommerce_presales", "product_consultation"
            risk_level = RiskLevel.R0
            confidence = max(confidence, 0.94)
            reason_codes.append("ECOMMERCE_PRESALES_RULE")
        elif self._contains(text, self._transaction_keywords):
            category, secondary = "transaction_dispute", "refund_request"
            risk_level = RiskLevel.R2
            confidence = max(confidence, 0.90)
            risk_tags.append("FINANCIAL_ACTION")
            reason_codes.append("FINANCIAL_ACTION_HARD_RULE")
        elif self._contains(text, self._billing_keywords):
            category, secondary = "billing_invoice", "billing_question"
            risk_level = RiskLevel.R1
            confidence = max(confidence, 0.88)
            risk_tags.append("FINANCIAL_INFORMATION")
            reason_codes.append("BILLING_TOPIC")
        elif self._contains(text, self._incident_keywords):
            category, secondary = "service_incident", "service_error"
            risk_level = RiskLevel.R1
            confidence = max(confidence, 0.86)
            risk_tags.append("TECHNICAL_INCIDENT")
            reason_codes.append("INCIDENT_SIGNAL")
        elif self._contains(text, self._howto_keywords):
            reason_codes.append("HOWTO_SIGNAL")
        elif self._contains(text, self._access_keywords):
            reason_codes.append("ACCESS_SIGNAL")
        elif category == "other_unclassified":
            reason_codes.append("NO_CONFIDENT_CATEGORY")

        return category, secondary, risk_level, confidence, reason_codes, risk_tags

    @staticmethod
    def _contains(text: str, keywords: set[str]) -> bool:
        return any(keyword in text for keyword in keywords)


def get_classifier() -> MockClassifier:
    return MockClassifier(gateway=get_model_gateway())

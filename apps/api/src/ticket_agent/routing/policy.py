from dataclasses import dataclass

from ticket_agent.classification.classifier import AnalysisResult
from ticket_agent.tickets.domain import Priority, RiskLevel


@dataclass(frozen=True)
class RoutingDecision:
    queue_id: str
    priority: Priority
    needs_human: bool
    human_reason: str | None
    matched_rule_id: str
    reason_codes: list[str]


class RoutingPolicy:
    """Deterministic policy used for the first vertical slice."""

    _category_defaults: dict[str, tuple[str, Priority, str]] = {
        "ecommerce_presales": (
            "ECOMMERCE_PRESALES",
            Priority.P3,
            "ROUTE-ECOM-PRESALES",
        ),
        "ecommerce_aftersales": (
            "ECOMMERCE_AFTERSALES",
            Priority.P1,
            "ROUTE-ECOM-AFTERSALES-HUMAN",
        ),
        "access_identity": ("IDENTITY_SUPPORT", Priority.P2, "ROUTE-ID-STD"),
        "product_howto": ("PRODUCT_SUPPORT", Priority.P3, "ROUTE-HOWTO-STD"),
        "service_incident": (
            "TECH_SERVICE_PLATFORM",
            Priority.P1,
            "ROUTE-INCIDENT",
        ),
        "billing_invoice": ("FINANCE_SUPPORT", Priority.P2, "ROUTE-BILLING"),
        "transaction_dispute": ("TRANSACTION_OPS", Priority.P1, "ROUTE-TXN-HUMAN"),
        "complaint_escalation": ("CUSTOMER_SUCCESS", Priority.P1, "ROUTE-COMPLAINT"),
        "data_privacy_security": ("SECURITY_RESPONSE", Priority.P0, "ROUTE-SECURITY"),
        "other_unclassified": ("MANUAL_TRIAGE", Priority.P2, "ROUTE-FALLBACK"),
    }

    _force_human_categories = {
        "ecommerce_aftersales",
        "billing_invoice",
        "transaction_dispute",
        "complaint_escalation",
        "data_privacy_security",
        "other_unclassified",
    }

    def decide(self, analysis: AnalysisResult) -> RoutingDecision:
        queue_id, priority, rule_id = self._category_defaults.get(
            analysis.category_primary,
            ("MANUAL_TRIAGE", Priority.P2, "ROUTE-FALLBACK"),
        )
        reason_codes = list(analysis.reason_codes)
        human_reason: str | None

        if analysis.risk_level in {RiskLevel.R2, RiskLevel.R3}:
            priority = Priority.P0 if analysis.risk_level == RiskLevel.R3 else priority
            needs_human = True
            human_reason = analysis.human_reason or "HIGH_RISK_TOPIC"
            reason_codes.append("RISK_FORCED_HUMAN")
        elif analysis.category_primary in self._force_human_categories:
            needs_human = True
            human_reason = "POLICY_REQUIRES_HUMAN_REVIEW"
            reason_codes.append("CATEGORY_HUMAN_REVIEW")
        else:
            needs_human = analysis.needs_human
            human_reason = analysis.human_reason

        return RoutingDecision(
            queue_id=queue_id,
            priority=priority,
            needs_human=needs_human,
            human_reason=human_reason,
            matched_rule_id=rule_id,
            reason_codes=list(dict.fromkeys(reason_codes)),
        )


def get_routing_policy() -> RoutingPolicy:
    return RoutingPolicy()


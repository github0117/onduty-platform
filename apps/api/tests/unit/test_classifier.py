from ticket_agent.classification.classifier import MockClassifier
from ticket_agent.tickets.domain import RiskLevel


def test_configuration_question_is_low_risk() -> None:
    result = MockClassifier().classify(
        subject="如何配置消息通知",
        body="请问管理员如何配置团队消息通知？",
        customer_tier="standard",
    )

    assert result.category_primary == "product_howto"
    assert result.category_secondary == "configuration"
    assert result.risk_level == RiskLevel.R0
    assert result.needs_human is False


def test_security_rule_cannot_be_downgraded_by_language() -> None:
    result = MockClassifier().classify(
        subject="想咨询账号问题",
        body="如果账号被盗并发生数据泄露，应该怎么处理？",
        customer_tier="standard",
    )

    assert result.category_primary == "data_privacy_security"
    assert result.risk_level == RiskLevel.R3
    assert result.needs_human is True
    assert result.human_reason == "HIGH_RISK_TOPIC"


def test_unknown_content_requires_human_review() -> None:
    result = MockClassifier().classify(
        subject="一个简短的问题",
        body="请帮忙看一下。",
        customer_tier="standard",
    )

    assert result.category_primary == "other_unclassified"
    assert result.needs_human is True


def test_ecommerce_presales_and_aftersales_are_routed_settlement_safely() -> None:
    presales = MockClassifier().classify(
        subject="雪地靴尺码和内里材质",
        body="请问雪地靴有哪些尺码，内里是什么材质？",
        customer_tier="standard",
    )
    aftersales = MockClassifier().classify(
        subject="雪地靴退货",
        body="商品不合适，订单如何申请退货退款？",
        customer_tier="standard",
    )

    assert presales.category_primary == "ecommerce_presales"
    assert presales.risk_level == RiskLevel.R0
    assert presales.needs_human is False
    assert aftersales.category_primary == "ecommerce_aftersales"
    assert aftersales.risk_level == RiskLevel.R1


def test_address_change_requires_human_review() -> None:
    result = MockClassifier().classify(
        subject="修改收货地址",
        body="订单 MOCK-ORD-1001 还没送到，我想改一下收货地址。",
        customer_tier="standard",
    )

    assert result.category_primary == "ecommerce_aftersales"
    assert result.category_secondary == "address_change"
    assert result.risk_level == RiskLevel.R2
    assert result.needs_human is True
    assert "ADDRESS_CHANGE_HARD_RULE" in result.reason_codes


def test_public_repository_documentation_is_low_risk() -> None:
    result = MockClassifier().classify(
        subject="公开 GitHub 仓库文档查询",
        body="请查询 modelcontextprotocol/python-sdk 的模块职责和项目文档结构。",
        customer_tier="standard",
    )

    assert result.category_primary == "product_howto"
    assert result.category_secondary == "technical_documentation"
    assert result.risk_level == RiskLevel.R0
    assert result.needs_human is False
    assert "TECHNICAL_DOCUMENTATION_RULE" in result.reason_codes


def test_private_repository_or_secret_request_requires_human_review() -> None:
    result = MockClassifier().classify(
        subject="查询私有 GitHub 仓库",
        body="请读取私有仓库源码并返回访问令牌和密钥。",
        customer_tier="standard",
    )

    assert result.category_primary == "data_privacy_security"
    assert result.risk_level == RiskLevel.R2
    assert result.needs_human is True


import json

import httpx

from ticket_agent.ecommerce.content_generation import (
    OpenAICompatibleListingContentGenerator,
)
from ticket_agent.ecommerce.markets import get_market_profile
from ticket_agent.ecommerce.models import EcommerceProduct
from ticket_agent.shared.settings import Settings


def _product() -> EcommerceProduct:
    return EcommerceProduct(
        business_unit_id="bu_demo",
        sku="SNOW-BOOT-001",
        name="加绒保暖雪地靴",
        category="雪地靴",
        brand="示例品牌",
        price=129.0,
        attributes_json={"鞋面": "牛剖层革", "内里": "短毛绒"},
        status="READY",
        created_by="test",
    )


def _fallback_content() -> dict[str, object]:
    return {
        "title": "本地雪地靴标题",
        "selling_points": ["本地卖点"],
        "detail_description": "本地详情",
        "short_video_script": [
            {"second": "0-3", "visual": "商品展示", "line": "本地脚本"}
        ],
        "hashtags": ["雪地靴"],
    }


def test_qwen_compatible_listing_generator_parses_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["Authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["model"] == "qwen-plus"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "title": "加绒雪地靴 橡胶底",
                                    "selling_points": [
                                        "短毛绒内里",
                                        "橡胶鞋底",
                                    ],
                                    "detail_description": (
                                        "鞋面采用牛剖层革，内里为短毛绒。"
                                    ),
                                    "short_video_script": [
                                        {
                                            "second": 0,
                                            "visual": "鞋面特写",
                                            "line": "先看鞋面材质",
                                        }
                                    ],
                                    "hashtags": ["雪地靴", "秋冬穿搭"],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    settings = Settings(
        ecommerce_content_provider="openai_compatible",
        ecommerce_content_base_url="https://qwen.example/v1",
        ecommerce_content_api_key="test-key",
        ecommerce_content_model_name="qwen-plus",
    )
    generator = OpenAICompatibleListingContentGenerator(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = generator.generate(
        product=_product(),
        profile=get_market_profile("CN"),
        sale_price=129.0,
        rule_context=["雪地靴必须描述材质和尺码"],
        fallback_content=_fallback_content(),
    )

    assert result.provider == "openai_compatible"
    assert result.model_name == "qwen-plus"
    assert result.fallback_used is False
    assert result.content["title"] == "加绒雪地靴 橡胶底"
    assert result.content["market_code"] == "CN"
    assert result.content["short_video_script"][0]["second"] == "0-15"


def test_qwen_listing_generator_falls_back_to_local_on_error() -> None:
    generator = OpenAICompatibleListingContentGenerator(
        Settings(
            ecommerce_content_provider="openai_compatible",
            ecommerce_content_base_url="https://qwen.example/v1",
            ecommerce_content_api_key="test-key",
            ecommerce_content_model_name="qwen-plus",
        ),
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(503, request=request)
            )
        ),
    )
    result = generator.generate(
        product=_product(),
        profile=get_market_profile("CN"),
        sale_price=129.0,
        rule_context=[],
        fallback_content=_fallback_content(),
    )

    assert result.provider == "local"
    assert result.fallback_used is True
    assert result.content["title"] == "本地雪地靴标题"

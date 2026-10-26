import base64
import json

import httpx

from ticket_agent.ecommerce.image_generation import (
    DashScopeOCRProductImageAuditor,
    DashScopeProductImageGenerator,
    LocalProductImageGenerator,
    OpenAICompatibleProductImageGenerator,
)
from ticket_agent.shared.settings import Settings

TINY_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff"
    b"\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_local_product_image_generator_is_deterministic() -> None:
    generator = LocalProductImageGenerator(dimensions=64)

    first = generator.generate(prompt="奶油色保温杯，简洁电商主图")
    second = generator.generate(prompt="奶油色保温杯，简洁电商主图")

    assert first.data == second.data
    assert first.content_type == "image/png"
    assert first.provider == "local"


def test_openai_compatible_image_generation_reads_b64() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "data": [
                    {"b64_json": base64.b64encode(TINY_PNG).decode("ascii")}
                ]
            },
        )

    generator = OpenAICompatibleProductImageGenerator(
        Settings(
            ecommerce_image_provider="openai_compatible",
            ecommerce_image_base_url="https://image.example/v1",
            ecommerce_image_model_name="image-model",
            ecommerce_image_fallback_to_local=False,
        ),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = generator.generate(prompt="商品主图")

    assert result.data == TINY_PNG
    assert result.content_type == "image/png"
    assert result.provider == "openai_compatible"
    assert captured["model"] == "image-model"
    assert captured["response_format"] == "b64_json"


def test_dashscope_image_generation_downloads_result() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            captured.update(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "output": {
                        "choices": [
                            {
                                "message": {
                                    "content": [
                                        {
                                            "image": (
                                                "https://image.example/result.png"
                                            )
                                        },
                                        {"text": "generated"},
                                    ]
                                }
                            }
                        ]
                    }
                },
            )
        return httpx.Response(
            200,
            content=TINY_PNG,
            headers={"Content-Type": "image/png"},
        )

    generator = DashScopeProductImageGenerator(
        Settings(
            ecommerce_image_provider="dashscope",
            ecommerce_image_base_url="https://dashscope.example",
            ecommerce_image_model_name="z-image-turbo",
            ecommerce_content_api_key="shared-key",
            ecommerce_image_fallback_to_local=False,
        ),
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
            follow_redirects=True,
        ),
    )

    result = generator.generate(prompt="雪地靴电商主图")

    assert result.data == TINY_PNG
    assert result.provider == "dashscope"
    assert result.model_name == "z-image-turbo"
    assert captured["model"] == "z-image-turbo"
    parameters = captured["parameters"]
    assert isinstance(parameters, dict)
    assert parameters["size"] == "1024*1024"


def test_dashscope_ocr_marks_images_with_text_for_review() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "qwen-vl-ocr"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "示例品牌 加绒雪地靴"
                        }
                    }
                ]
            },
        )

    auditor = DashScopeOCRProductImageAuditor(
        Settings(
            ecommerce_visual_audit_provider="dashscope_ocr",
            ecommerce_visual_audit_model_name="qwen-vl-ocr",
            ecommerce_content_api_key="shared-key",
        ),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = auditor.audit(data=TINY_PNG, content_type="image/png")

    assert result.provider == "dashscope_ocr"
    assert result.status == "NEEDS_REVIEW"
    assert result.extracted_text == "示例品牌 加绒雪地靴"

import base64
import json

import httpx
import pytest

from ticket_agent.knowledge.ocr import (
    DashScopeChatOCR,
    OCRUnavailableError,
    get_ocr_provider,
)
from ticket_agent.shared.settings import Settings


def _settings() -> Settings:
    return Settings(
        app_env="test",
        knowledge_ocr_provider="dashscope",
        knowledge_ocr_base_url="https://ocr.example.test/v1",
        knowledge_ocr_api_key="test-key",
        knowledge_ocr_model_name="qwen-vl-ocr",
    )


def test_provider_disabled_by_default() -> None:
    # 显式给默认值，避免本机/CI 的 .env 注入 KNOWLEDGE_OCR_PROVIDER。
    assert get_ocr_provider(Settings(app_env="test", knowledge_ocr_provider="none")) is None


def test_dashscope_ocr_posts_image_and_returns_text() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "  第一行\n第二行 "}}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = DashScopeChatOCR(_settings(), client=client)
    result = provider.extract_text(data=b"\x89PNG\r\n", content_type="image/png")

    assert result.text == "第一行\n第二行"
    assert result.provider == "dashscope"
    assert result.model_name == "qwen-vl-ocr"
    assert captured["url"] == "https://ocr.example.test/v1/chat/completions"
    assert captured["authorization"] == "Bearer test-key"
    body = captured["body"]
    assert isinstance(body, dict)
    content = body["messages"][0]["content"]
    assert content[0]["type"] == "image_url"
    encoded = base64.b64encode(b"\x89PNG\r\n").decode("ascii")
    assert content[0]["image_url"]["url"] == f"data:image/png;base64,{encoded}"
    assert content[1]["type"] == "text"


def test_dashscope_ocr_accepts_content_parts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"type": "text", "text": "A"},
                                {"type": "text", "text": "B"},
                            ]
                        }
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = DashScopeChatOCR(_settings(), client=client).extract_text(
        data=b"png",
        content_type="image/png",
    )

    assert result.text == "A\nB"


@pytest.mark.parametrize("content", ["", "0", "无", "无文字"])
def test_dashscope_ocr_normalizes_empty_markers(content: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = DashScopeChatOCR(_settings(), client=client).extract_text(
        data=b"png",
        content_type="image/png",
    )

    assert result.text == ""


def test_dashscope_ocr_rejects_non_image_payload() -> None:
    with pytest.raises(OCRUnavailableError):
        DashScopeChatOCR(_settings()).extract_text(
            data=b"text",
            content_type="text/plain",
        )


def test_dashscope_ocr_requires_endpoint_and_model() -> None:
    # OCR falls back to MODEL_* when its own endpoint is empty, so a local
    # .env with a real model must be neutralised for this case.
    settings = Settings(
        app_env="test",
        knowledge_ocr_provider="dashscope",
        knowledge_ocr_base_url="",
        knowledge_ocr_model_name="",
        model_base_url="",
        model_name="",
    )
    with pytest.raises(OCRUnavailableError):
        DashScopeChatOCR(settings).extract_text(data=b"png", content_type="image/png")


def test_dashscope_ocr_maps_http_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(500, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(OCRUnavailableError):
        DashScopeChatOCR(_settings(), client=client).extract_text(
            data=b"png",
            content_type="image/png",
        )


def test_dashscope_ocr_requires_response_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"choices": [{"message": {"content": None}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(OCRUnavailableError):
        DashScopeChatOCR(_settings(), client=client).extract_text(
            data=b"png",
            content_type="image/png",
        )


def test_ocr_credentials_inherit_from_model_settings() -> None:
    settings = Settings(
        app_env="test",
        knowledge_ocr_provider="dashscope",
        # 显式留空才会触发继承；否则本机 .env 的 OCR 配置会覆盖默认值。
        knowledge_ocr_base_url="",
        knowledge_ocr_api_key="",
        knowledge_ocr_model_name="",
        model_base_url="https://model.example.test/v1",
        model_api_key="model-key",
        model_name="qwen-plus",
    )

    assert settings.knowledge_ocr_base_url == "https://model.example.test/v1"
    assert settings.knowledge_ocr_api_key == "model-key"
    assert settings.knowledge_ocr_model_name == "qwen-plus"

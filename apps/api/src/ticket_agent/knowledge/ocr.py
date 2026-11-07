import base64
from dataclasses import dataclass
from typing import Protocol, cast

import httpx

from ticket_agent.shared.settings import Settings, get_settings

_EMPTY_MARKERS = {"", "0", "无", "无文字"}
_OCR_PROMPT = (
    "提取图片中所有实际可见文字，保持原有阅读顺序。"
    "只返回文字；没有文字时返回空。"
)


class OCRUnavailableError(Exception):
    """OCR provider is not configured or could not return usable text."""


@dataclass(frozen=True)
class OCRResult:
    text: str
    provider: str
    model_name: str


class OCRProvider(Protocol):
    name: str

    def extract_text(self, *, data: bytes, content_type: str) -> OCRResult: ...


class DashScopeChatOCR:
    """OCR through an OpenAI-compatible vision chat endpoint.

    DashScope exposes ``qwen-vl-ocr`` both natively and through its
    compatible-mode gateway, so the same protocol also works for any
    OpenAI-compatible multimodal endpoint.
    """

    name = "dashscope"

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self._client = client

    def extract_text(self, *, data: bytes, content_type: str) -> OCRResult:
        if not content_type.startswith("image/"):
            raise OCRUnavailableError("Knowledge OCR requires an image payload.")
        base_url = self.settings.knowledge_ocr_base_url.strip()
        model_name = self.settings.knowledge_ocr_model_name.strip()
        if not base_url or not model_name:
            raise OCRUnavailableError(
                "Knowledge OCR base URL and model name are required."
            )
        encoded = base64.b64encode(data).decode("ascii")
        headers = {"Content-Type": "application/json"}
        api_key = self.settings.knowledge_ocr_api_key
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            response = self._post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers=headers,
                body={
                    "model": model_name,
                    "temperature": 0,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": (
                                            f"data:{content_type};base64,{encoded}"
                                        )
                                    },
                                },
                                {"type": "text", "text": _OCR_PROMPT},
                            ],
                        }
                    ],
                },
            )
            response.raise_for_status()
            payload = cast(object, response.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise OCRUnavailableError("Knowledge OCR request failed.") from exc
        text = _response_text(payload)
        if text is None:
            raise OCRUnavailableError("Knowledge OCR response is missing text.")
        normalized = text.strip()
        if normalized in _EMPTY_MARKERS:
            normalized = ""
        return OCRResult(
            text=normalized,
            provider=self.name,
            model_name=model_name,
        )

    def _post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: dict[str, object],
    ) -> httpx.Response:
        if self._client is not None:
            return self._client.post(url, headers=headers, json=body)
        with httpx.Client(
            timeout=self.settings.knowledge_ocr_timeout_seconds
        ) as client:
            return client.post(url, headers=headers, json=body)


def get_ocr_provider(settings: Settings | None = None) -> OCRProvider | None:
    resolved = settings or get_settings()
    if resolved.knowledge_ocr_provider == "dashscope":
        return DashScopeChatOCR(resolved)
    return None


def _response_text(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    message = first.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
        return "\n".join(parts) if parts else None
    return None


__all__ = [
    "DashScopeChatOCR",
    "OCRProvider",
    "OCRResult",
    "OCRUnavailableError",
    "get_ocr_provider",
]

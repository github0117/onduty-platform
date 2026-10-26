import base64
import hashlib
import struct
import zlib
from dataclasses import dataclass
from typing import Protocol

import httpx

from ticket_agent.shared.redaction import redact_sensitive_text
from ticket_agent.shared.settings import Settings, get_settings


class ImageGenerationError(Exception):
    pass


class ImageVisualAuditError(Exception):
    pass


@dataclass(frozen=True)
class GeneratedImage:
    data: bytes
    content_type: str
    provider: str
    model_name: str
    fallback_used: bool


@dataclass(frozen=True)
class ImageVisualAudit:
    provider: str
    model_name: str
    extracted_text: str
    status: str


class ProductImageGenerator(Protocol):
    def generate(self, *, prompt: str) -> GeneratedImage: ...


class ProductImageVisualAuditor(Protocol):
    def audit(
        self,
        *,
        data: bytes,
        content_type: str,
    ) -> ImageVisualAudit: ...


class LocalProductImageGenerator:
    def __init__(self, dimensions: int = 512) -> None:
        self.dimensions = dimensions

    def generate(self, *, prompt: str) -> GeneratedImage:
        digest = hashlib.sha256(prompt.encode("utf-8")).digest()
        color = (48 + digest[0] % 120, 70 + digest[1] % 120, 90 + digest[2] % 120)
        return GeneratedImage(
            data=_gradient_png(self.dimensions, color),
            content_type="image/png",
            provider="local",
            model_name="local-product-image-v1",
            fallback_used=False,
        )


class OpenAICompatibleProductImageGenerator:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self._client = client or httpx.Client(
            timeout=settings.ecommerce_image_timeout_seconds
        )
        self._local = LocalProductImageGenerator()

    def generate(self, *, prompt: str) -> GeneratedImage:
        try:
            image = self._generate_remote(prompt)
            return GeneratedImage(
                data=image,
                content_type=_image_content_type(image),
                provider="openai_compatible",
                model_name=self.settings.ecommerce_image_model_name,
                fallback_used=False,
            )
        except (httpx.HTTPError, ImageGenerationError, ValueError) as exc:
            if not self.settings.ecommerce_image_fallback_to_local:
                raise ImageGenerationError(str(exc)) from exc
            local = self._local.generate(prompt=prompt)
            return GeneratedImage(
                data=local.data,
                content_type=local.content_type,
                provider=local.provider,
                model_name=local.model_name,
                fallback_used=True,
            )

    def _generate_remote(self, prompt: str) -> bytes:
        base_url = (
            self.settings.ecommerce_image_base_url
            or self.settings.model_base_url
        )
        if not base_url or not self.settings.ecommerce_image_model_name:
            raise ImageGenerationError(
                "Image generation base URL and model name are required"
            )
        headers = {"Content-Type": "application/json"}
        api_key = (
            self.settings.ecommerce_image_api_key
            or self.settings.model_api_key
        )
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        safe_prompt = (
            redact_sensitive_text(prompt)
            if self.settings.model_data_redaction_enabled
            else prompt
        )
        response = self._client.post(
            f"{base_url.rstrip('/')}/images/generations",
            headers=headers,
            json={
                "model": self.settings.ecommerce_image_model_name,
                "prompt": safe_prompt,
                "size": "1024x1024",
                "n": 1,
                "response_format": "b64_json",
            },
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data")
        if not isinstance(data, list) or not data:
            raise ImageGenerationError("Image response data is missing")
        item = data[0]
        if not isinstance(item, dict) or not isinstance(item.get("b64_json"), str):
            raise ImageGenerationError("Image response does not contain b64_json")
        image = base64.b64decode(item["b64_json"], validate=True)
        if len(image) < 24:
            raise ImageGenerationError("Generated image is empty")
        return image


class DashScopeProductImageGenerator:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self._client = client or httpx.Client(
            timeout=settings.ecommerce_image_timeout_seconds,
            follow_redirects=True,
        )
        self._local = LocalProductImageGenerator()

    def generate(self, *, prompt: str) -> GeneratedImage:
        try:
            image = self._generate_remote(prompt)
            return GeneratedImage(
                data=image,
                content_type=_image_content_type(image),
                provider="dashscope",
                model_name=self.settings.ecommerce_image_model_name,
                fallback_used=False,
            )
        except (httpx.HTTPError, ImageGenerationError, ValueError) as exc:
            if not self.settings.ecommerce_image_fallback_to_local:
                raise ImageGenerationError(str(exc)) from exc
            local = self._local.generate(prompt=prompt)
            return GeneratedImage(
                data=local.data,
                content_type=local.content_type,
                provider=local.provider,
                model_name=local.model_name,
                fallback_used=True,
            )

    def _generate_remote(self, prompt: str) -> bytes:
        base_url = (
            self.settings.ecommerce_image_base_url
            or "https://dashscope.aliyuncs.com"
        )
        api_key = (
            self.settings.ecommerce_image_api_key
            or self.settings.ecommerce_content_api_key
            or self.settings.model_api_key
        )
        if not api_key or not self.settings.ecommerce_image_model_name:
            raise ImageGenerationError(
                "DashScope image API key and model name are required"
            )
        safe_prompt = (
            redact_sensitive_text(prompt)
            if self.settings.model_data_redaction_enabled
            else prompt
        )
        response = self._client.post(
            (
                f"{base_url.rstrip('/')}"
                "/api/v1/services/aigc/multimodal-generation/generation"
            ),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.settings.ecommerce_image_model_name,
                "input": {
                    "messages": [
                        {
                            "role": "user",
                            "content": [{"text": safe_prompt}],
                        }
                    ]
                },
                "parameters": {
                    "size": "1024*1024",
                    "n": 1,
                    "watermark": False,
                    "prompt_extend": False,
                },
            },
        )
        response.raise_for_status()
        payload = response.json()
        output = payload.get("output")
        choices = output.get("choices") if isinstance(output, dict) else None
        if not isinstance(choices, list) or not choices:
            raise ImageGenerationError("DashScope image response has no choices")
        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            raise ImageGenerationError("DashScope image response has no content")
        image_url = next(
            (
                item["image"]
                for item in content
                if isinstance(item, dict) and isinstance(item.get("image"), str)
            ),
            None,
        )
        if not image_url:
            raise ImageGenerationError("DashScope image URL is missing")
        image_response = self._client.get(image_url)
        image_response.raise_for_status()
        image = image_response.content
        if len(image) < 24:
            raise ImageGenerationError("DashScope generated image is empty")
        return image


class DashScopeOCRProductImageAuditor:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self._client = client or httpx.Client(
            timeout=settings.ecommerce_visual_audit_timeout_seconds
        )

    def audit(
        self,
        *,
        data: bytes,
        content_type: str,
    ) -> ImageVisualAudit:
        api_key = (
            self.settings.ecommerce_content_api_key
            or self.settings.model_api_key
        )
        if not api_key or not self.settings.ecommerce_visual_audit_model_name:
            raise ImageVisualAuditError(
                "Visual audit API key and model name are required"
            )
        if not content_type.startswith("image/"):
            raise ImageVisualAuditError("Visual audit requires an image")
        encoded = base64.b64encode(data).decode("ascii")
        response = self._client.post(
            (
                "https://dashscope.aliyuncs.com/compatible-mode/v1/"
                "chat/completions"
            ),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.settings.ecommerce_visual_audit_model_name,
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
                            {
                                "type": "text",
                                "text": (
                                    "提取图片中所有实际可见文字，只返回文字。"
                                    "没有文字时返回 0。"
                                ),
                            },
                        ],
                    }
                ],
            },
        )
        response.raise_for_status()
        payload = response.json()
        choices = payload.get("choices")
        first = choices[0] if isinstance(choices, list) and choices else None
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ImageVisualAuditError("Visual audit response is missing text")
        extracted = content.strip()
        if extracted in {"", "0", "无", "无文字"}:
            extracted = ""
        return ImageVisualAudit(
            provider="dashscope_ocr",
            model_name=self.settings.ecommerce_visual_audit_model_name,
            extracted_text=extracted[:2000],
            status="NEEDS_REVIEW" if extracted else "PASS",
        )


def get_product_image_generator(
    settings: Settings | None = None,
) -> ProductImageGenerator:
    resolved = settings or get_settings()
    if resolved.ecommerce_image_provider == "dashscope":
        return DashScopeProductImageGenerator(resolved)
    if resolved.ecommerce_image_provider == "openai_compatible":
        return OpenAICompatibleProductImageGenerator(resolved)
    return LocalProductImageGenerator()


def get_product_image_visual_auditor(
    settings: Settings | None = None,
) -> ProductImageVisualAuditor | None:
    resolved = settings or get_settings()
    if resolved.ecommerce_visual_audit_provider == "dashscope_ocr":
        return DashScopeOCRProductImageAuditor(resolved)
    return None


def _image_content_type(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    raise ImageGenerationError("Generated file is not a supported image")


def _gradient_png(dimensions: int, color: tuple[int, int, int]) -> bytes:
    rows = bytearray()
    red, green, blue = color
    for y in range(dimensions):
        rows.append(0)
        for x in range(dimensions):
            center = ((x - dimensions / 2) ** 2 + (y - dimensions / 2) ** 2) ** 0.5
            ring = int(center / (dimensions / 8)) % 2 == 0
            light = 0.62 + 0.32 * (y / dimensions)
            if ring:
                rows.extend(
                    (
                        min(255, int(red * light) + 18),
                        min(255, int(green * light) + 18),
                        min(255, int(blue * light) + 18),
                    )
                )
            else:
                rows.extend((245, 248, 249))

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + chunk_type
            + data
            + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
        )

    header = struct.pack(
        ">IIBBBBB",
        dimensions,
        dimensions,
        8,
        2,
        0,
        0,
        0,
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )

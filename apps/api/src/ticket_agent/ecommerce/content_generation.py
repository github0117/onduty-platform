import json
import re
from dataclasses import dataclass
from typing import Protocol, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ticket_agent.ecommerce.markets import MarketProfile
from ticket_agent.ecommerce.models import EcommerceProduct
from ticket_agent.shared.redaction import redact_sensitive_text
from ticket_agent.shared.settings import Settings, get_settings


class ContentGenerationError(Exception):
    pass


class GeneratedVideoScene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    second: str | int | float
    visual: str = Field(min_length=1, max_length=300)
    line: str = Field(min_length=1, max_length=1000)


class GeneratedListingContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    selling_points: list[str] = Field(min_length=1, max_length=5)
    detail_description: str = Field(min_length=1, max_length=5000)
    short_video_script: list[GeneratedVideoScene] = Field(
        min_length=1,
        max_length=8,
    )
    hashtags: list[str] = Field(default_factory=list, max_length=10)


@dataclass(frozen=True)
class ListingContentResult:
    content: dict[str, object]
    provider: str
    model_name: str
    fallback_used: bool


class ListingContentGenerator(Protocol):
    def generate(
        self,
        *,
        product: EcommerceProduct,
        profile: MarketProfile,
        sale_price: float,
        rule_context: list[str],
        fallback_content: dict[str, object],
    ) -> ListingContentResult: ...


class LocalListingContentGenerator:
    def generate(
        self,
        *,
        product: EcommerceProduct,
        profile: MarketProfile,
        sale_price: float,
        rule_context: list[str],
        fallback_content: dict[str, object],
    ) -> ListingContentResult:
        del product, sale_price, rule_context
        return ListingContentResult(
            content=fallback_content,
            provider="local",
            model_name=(
                "ecommerce-listing-template-v1"
                if profile.code == "CN"
                else "ecommerce-market-template-v1"
            ),
            fallback_used=False,
        )


class OpenAICompatibleListingContentGenerator:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self._client = client or httpx.Client(
            timeout=settings.ecommerce_content_timeout_seconds
        )
        self._local = LocalListingContentGenerator()

    def generate(
        self,
        *,
        product: EcommerceProduct,
        profile: MarketProfile,
        sale_price: float,
        rule_context: list[str],
        fallback_content: dict[str, object],
    ) -> ListingContentResult:
        try:
            content = self._generate_remote(
                product=product,
                profile=profile,
                sale_price=sale_price,
                rule_context=rule_context,
            )
            return ListingContentResult(
                content=content,
                provider="openai_compatible",
                model_name=self.settings.ecommerce_content_model_name,
                fallback_used=False,
            )
        except (httpx.HTTPError, ContentGenerationError, ValidationError) as exc:
            if not self.settings.ecommerce_content_fallback_to_local:
                raise ContentGenerationError(str(exc)) from exc
            local = self._local.generate(
                product=product,
                profile=profile,
                sale_price=sale_price,
                rule_context=rule_context,
                fallback_content=fallback_content,
            )
            return ListingContentResult(
                content=local.content,
                provider=local.provider,
                model_name=local.model_name,
                fallback_used=True,
            )

    def _generate_remote(
        self,
        *,
        product: EcommerceProduct,
        profile: MarketProfile,
        sale_price: float,
        rule_context: list[str],
    ) -> dict[str, object]:
        base_url = (
            self.settings.ecommerce_content_base_url
            or self.settings.model_base_url
        )
        api_key = (
            self.settings.ecommerce_content_api_key
            or self.settings.model_api_key
        )
        if not base_url or not self.settings.ecommerce_content_model_name:
            raise ContentGenerationError(
                "E-commerce content base URL and model name are required"
            )
        prompt = {
            "market_code": profile.code,
            "locale": profile.locale,
            "currency": profile.currency,
            "sale_price": sale_price,
            "product": {
                "sku": product.sku,
                "name": product.name,
                "category": product.category,
                "brand": product.brand,
                "attributes": product.attributes_json,
            },
            "market_rules": rule_context,
        }
        system = (
            "你是电商商品内容编辑。只输出严格 JSON，不输出 Markdown。"
            "不得编造商品参数、认证或功效。输出字段必须为 title、"
            "selling_points、detail_description、short_video_script、hashtags。"
            "selling_points 为 1 到 5 条，short_video_script 每项包含 "
            "second、visual、line。second 使用类似 0-3、3-6 的字符串。"
            "只能陈述 product.attributes 中明确存在的事实；不得使用实测、"
            "认证、防滑、锁温、稳定抓地、耐穿、不勒、不卡、温度区间或百分比，"
            "除非这些内容原样出现在商品属性中。"
        )
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        safe_prompt = json.dumps(prompt, ensure_ascii=False)
        if self.settings.model_data_redaction_enabled:
            safe_prompt = redact_sensitive_text(safe_prompt)
        response = self._client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json={
                "model": self.settings.ecommerce_content_model_name,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": safe_prompt},
                ],
            },
        )
        response.raise_for_status()
        payload = response.json()
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ContentGenerationError("Content response has no choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        raw = message.get("content") if isinstance(message, dict) else None
        if not isinstance(raw, str):
            raise ContentGenerationError("Content response is missing text")
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            parsed = json.loads(cleaned)
        except ValueError as exc:
            raise ContentGenerationError("Content response is not valid JSON") from exc
        generated = GeneratedListingContent.model_validate(parsed)
        content = generated.model_dump()
        _validate_generated_claims(content, product)
        content["short_video_script"] = _normalize_video_timeline(
            content["short_video_script"]
        )
        content["market_code"] = profile.code
        content["locale"] = profile.locale
        return content


def get_listing_content_generator(
    settings: Settings | None = None,
) -> ListingContentGenerator:
    resolved = settings or get_settings()
    if resolved.ecommerce_content_provider == "openai_compatible":
        return OpenAICompatibleListingContentGenerator(resolved)
    return LocalListingContentGenerator()


def _normalize_video_timeline(
    scenes: list[dict[str, object]],
) -> list[dict[str, object]]:
    normalized = [dict(scene) for scene in scenes]
    numeric_starts = [
        float(cast(int | float, scene["second"]))
        for scene in normalized
        if isinstance(scene.get("second"), (int, float))
    ]
    for index, scene in enumerate(normalized):
        value = scene.get("second")
        if not isinstance(value, (int, float)):
            continue
        start = float(value)
        next_numeric = next(
            (
                float(cast(int | float, later["second"]))
                for later in normalized[index + 1 :]
                if isinstance(later.get("second"), (int, float))
            ),
            15.0,
        )
        end = next_numeric if next_numeric > start else min(15.0, start + 3)
        scene["second"] = f"{_format_second(start)}-{_format_second(end)}"
    if not numeric_starts:
        return normalized
    return normalized


def _format_second(value: float) -> str:
    return str(int(value)) if value.is_integer() else f"{value:.1f}"


def _validate_generated_claims(
    content: dict[str, object],
    product: EcommerceProduct,
) -> None:
    text = json.dumps(content, ensure_ascii=False)
    trusted = json.dumps(product.attributes_json, ensure_ascii=False)
    unsupported_terms = (
        "实测",
        "认证",
        "防滑",
        "锁温",
        "稳定抓地",
        "耐穿",
        "不勒",
        "不卡",
    )
    violations = [
        term for term in unsupported_terms if term in text and term not in trusted
    ]
    if "℃" in text or "°C" in text:
        violations.append("temperature_claim")
    if "%" in text:
        violations.append("percentage_claim")
    if violations:
        raise ContentGenerationError(
            "Generated content contains unsupported claims: "
            + ", ".join(violations)
        )

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketProfile:
    code: str
    name: str
    locale: str
    currency: str
    country_code: str
    restricted_claims: tuple[str, ...]


MARKET_PROFILES: dict[str, MarketProfile] = {
    "CN": MarketProfile(
        code="CN",
        name="中国站",
        locale="zh-CN",
        currency="CNY",
        country_code="CN",
        restricted_claims=(
            "国家级",
            "世界第一",
            "绝对安全",
            "百分之百",
            "100%有效",
            "包治百病",
        ),
    ),
    "US": MarketProfile(
        code="US",
        name="Amazon US",
        locale="en-US",
        currency="USD",
        country_code="US",
        restricted_claims=(
            "FDA approved",
            "cures",
            "best in the world",
            "100% safe",
            "guaranteed results",
        ),
    ),
}


def get_market_profile(code: str) -> MarketProfile | None:
    return MARKET_PROFILES.get(code.upper())

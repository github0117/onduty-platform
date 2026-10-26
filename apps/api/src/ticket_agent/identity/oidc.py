import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx
import jwt

from ticket_agent.identity.models import Principal
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import Settings, get_settings

_SUPPORTED_ALGORITHMS = {"RS256", "RS384", "RS512", "PS256", "ES256"}
_KNOWN_ROLES = {
    "requester",
    "agent",
    "supervisor",
    "knowledge_operator",
    "business_manager",
    "admin",
    "auditor",
}
_ROLE_ALIASES = {
    "support_agent": "agent",
    "ticket_agent": "agent",
    "ticket_supervisor": "supervisor",
    "support_supervisor": "supervisor",
    "security_auditor": "auditor",
}
_ROLE_FALLBACK_CLAIMS = ("realm_access.roles", "groups")


@dataclass(frozen=True)
class _KeyCache:
    keys: dict[str, Any]
    expires_at: float


class OIDCAuthenticator:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._lock = threading.Lock()
        self._cache: _KeyCache | None = None
        self._jwks_url: str | None = self.settings.oidc_jwks_url or None

    def authenticate(self, token: str) -> Principal:
        self._validate_configuration()
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise self._unauthorized("Bearer token is malformed.") from exc

        algorithm = str(header.get("alg", ""))
        if algorithm not in _SUPPORTED_ALGORITHMS:
            raise self._unauthorized("Bearer token uses an unsupported signing algorithm.")

        kid = str(header.get("kid", ""))
        key = self._get_key(kid)
        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=[algorithm],
                audience=self.settings.oidc_audience,
                issuer=self.settings.oidc_issuer_url,
                options={
                    "require": ["exp", "iat", "iss", "aud", "sub"],
                    "verify_aud": True,
                    "verify_iss": True,
                },
                leeway=30,
            )
        except jwt.InvalidTokenError as exc:
            raise self._unauthorized("Bearer token validation failed.") from exc

        actor_id = str(claims["sub"])
        role = resolve_role(claims, self.settings.oidc_roles_claim)
        customer_ref = self._resolve_customer_ref(claims, actor_id)
        business_units = self._resolve_business_units(claims)
        if not business_units:
            raise ApiProblem(
                status_code=403,
                code="BUSINESS_UNIT_CONTEXT_REQUIRED",
                title="Business unit context required",
                detail="The OIDC token has no authorized business unit.",
            )
        return Principal(
            actor_id=actor_id,
            role=role,
            service_identity="human.oidc",
            customer_ref=customer_ref,
            issuer=str(claims["iss"]),
            business_units=business_units,
        )

    def _get_key(self, kid: str) -> Any:
        keys = self._get_keys()
        if kid and kid in keys:
            return keys[kid]
        if not kid and len(keys) == 1:
            return next(iter(keys.values()))

        # A missing key ID commonly means the provider rotated signing keys.
        keys = self._get_keys(force_refresh=True)
        if kid and kid in keys:
            return keys[kid]
        if not kid and len(keys) == 1:
            return next(iter(keys.values()))
        raise self._unauthorized("Bearer token signing key is not available.")

    def _get_keys(self, *, force_refresh: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if not force_refresh and self._cache and self._cache.expires_at > now:
            return self._cache.keys

        with self._lock:
            now = time.monotonic()
            if not force_refresh and self._cache and self._cache.expires_at > now:
                return self._cache.keys
            jwks_url = self._resolve_jwks_url()
            payload = self._fetch_json(jwks_url)
            keys = self._parse_jwks(payload)
            self._cache = _KeyCache(
                keys=keys,
                expires_at=now + self.settings.oidc_jwks_cache_seconds,
            )
            return keys

    def _resolve_jwks_url(self) -> str:
        if self._jwks_url:
            return self._jwks_url
        discovery_url = (
            f"{self.settings.oidc_issuer_url.rstrip('/')}/.well-known/openid-configuration"
        )
        payload = self._fetch_json(discovery_url)
        jwks_uri = payload.get("jwks_uri")
        if not isinstance(jwks_uri, str) or not jwks_uri:
            raise ApiProblem(
                status_code=503,
                code="OIDC_DISCOVERY_FAILED",
                title="OIDC discovery failed",
                detail="The OIDC discovery document does not contain jwks_uri.",
            )
        self._jwks_url = jwks_uri
        return jwks_uri

    def _fetch_json(self, url: str) -> Mapping[str, Any]:
        try:
            response = httpx.get(url, timeout=self.settings.oidc_http_timeout_seconds)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ApiProblem(
                status_code=503,
                code="OIDC_PROVIDER_UNAVAILABLE",
                title="OIDC provider is unavailable",
                detail="Unable to load OIDC configuration or signing keys.",
                retryable=True,
            ) from exc
        if not isinstance(payload, Mapping):
            raise ApiProblem(
                status_code=503,
                code="OIDC_DISCOVERY_FAILED",
                title="OIDC discovery failed",
                detail="The OIDC endpoint returned an invalid document.",
            )
        return payload

    @staticmethod
    def _parse_jwks(payload: Mapping[str, Any]) -> dict[str, Any]:
        raw_keys = payload.get("keys")
        if not isinstance(raw_keys, list) or not raw_keys:
            raise ApiProblem(
                status_code=503,
                code="OIDC_DISCOVERY_FAILED",
                title="OIDC JWKS is invalid",
                detail="The OIDC provider did not return any signing keys.",
            )

        parsed: dict[str, Any] = {}
        for raw_key in raw_keys:
            if not isinstance(raw_key, Mapping):
                continue
            kid = str(raw_key.get("kid", ""))
            try:
                key = jwt.PyJWK.from_dict(dict(raw_key))
            except jwt.InvalidTokenError:
                continue
            if key.algorithm_name in _SUPPORTED_ALGORITHMS:
                parsed[kid] = key.key
        if not parsed:
            raise ApiProblem(
                status_code=503,
                code="OIDC_DISCOVERY_FAILED",
                title="OIDC JWKS is invalid",
                detail="No supported signing keys were found.",
            )
        return parsed

    def _resolve_business_units(
        self,
        claims: Mapping[str, Any],
    ) -> tuple[str, ...]:
        raw = claims.get(self.settings.oidc_business_units_claim)
        if raw is None:
            raw = claims.get("business_unit_id")
        values: list[str] = []
        if isinstance(raw, str):
            values.append(raw)
        elif isinstance(raw, list):
            values.extend(
                str(value)
                for value in raw
                if isinstance(value, str)
            )
        return tuple(
            dict.fromkeys(
                value.strip()
                for value in values
                if value.strip()
            )
        )

    def _resolve_customer_ref(self, claims: Mapping[str, Any], actor_id: str) -> str:
        configured_claim = self.settings.oidc_customer_ref_claim
        if configured_claim:
            value = read_claim(claims, configured_claim)
            if isinstance(value, str) and value:
                return value
        fallback = claims.get("customer_ref")
        return str(fallback) if isinstance(fallback, str) and fallback else actor_id

    def _validate_configuration(self) -> None:
        if not self.settings.oidc_issuer_url or not self.settings.oidc_audience:
            raise ApiProblem(
                status_code=503,
                code="OIDC_NOT_CONFIGURED",
                title="OIDC authentication is not configured",
                detail="OIDC issuer URL and audience must be configured.",
            )

    @staticmethod
    def _unauthorized(detail: str) -> ApiProblem:
        return ApiProblem(
            status_code=401,
            code="UNAUTHENTICATED",
            title="Authentication failed",
            detail=detail,
        )


def resolve_role(claims: Mapping[str, Any], claim_name: str) -> str:
    raw_roles = read_claim(claims, claim_name)
    if raw_roles is None:
        for fallback_claim in _ROLE_FALLBACK_CLAIMS:
            raw_roles = read_claim(claims, fallback_claim)
            if raw_roles is not None:
                break

    values: list[str]
    if isinstance(raw_roles, str):
        values = [raw_roles]
    elif isinstance(raw_roles, list):
        values = [str(item) for item in raw_roles]
    else:
        values = []

    normalized = {normalize_role(value) for value in values}
    for role in (
        "admin",
        "supervisor",
        "knowledge_operator",
        "business_manager",
        "auditor",
        "agent",
        "requester",
    ):
        if role in normalized:
            return role
    return "requester"


def normalize_role(value: str) -> str:
    candidate = value.strip().rstrip("/").rsplit("/", 1)[-1].lower().replace("-", "_")
    candidate = _ROLE_ALIASES.get(candidate, candidate)
    return candidate if candidate in _KNOWN_ROLES else "requester"


def read_claim(claims: Mapping[str, Any], path: str) -> Any:
    current: Any = claims
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


@lru_cache
def get_oidc_authenticator() -> OIDCAuthenticator:
    return OIDCAuthenticator()


"""Common adapter contracts for external connectors."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

from ticket_agent.shared.settings import get_settings

CONNECTOR_TYPES = ("email", "http_json")
DIRECTIONS = ("INBOUND", "OUTBOUND", "BIDIRECTIONAL")
STATUSES = ("ACTIVE", "DISABLED")

# Keys that look like credentials must never be persisted in connector config.
SECRET_KEY_MARKERS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "access_key",
    "credential",
)


class ConnectorError(Exception):
    """Typed connector failure with an explicit retry contract."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class InboundEnvelope:
    external_message_id: str
    external_conversation_id: str
    external_user_id: str
    content: str
    subject: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InboundFetch:
    envelope: InboundEnvelope
    ack_token: str


@dataclass(frozen=True)
class OutboundEnvelope:
    recipient: str
    subject: str
    content: str
    message_id: str
    in_reply_to: str | None = None
    thread_id: str | None = None


@dataclass(frozen=True)
class DeliveryReceipt:
    external_message_id: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HealthCheck:
    healthy: bool
    detail: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class InboundChannelAdapter(Protocol):
    def health(self) -> HealthCheck: ...

    def fetch_inbound(self, *, limit: int) -> list[InboundFetch]: ...

    def acknowledge(self, token: str) -> None: ...


class OutboundChannelAdapter(Protocol):
    def health(self) -> HealthCheck: ...

    def send(self, message: OutboundEnvelope) -> DeliveryReceipt: ...


class ReadOnlyAdapter(Protocol):
    def health(self) -> HealthCheck: ...

    def query(self, params: dict[str, str]) -> dict[str, Any]: ...


def resolve_secret(secret_ref: str | None) -> str:
    """Resolve a credential by environment-variable name only."""
    if not secret_ref:
        raise ConnectorError(
            "CONNECTOR_SECRET_NOT_CONFIGURED",
            "Connector has no secret_ref configured.",
        )
    value = os.environ.get(secret_ref, "").strip()
    if value:
        return value
    raw_map = get_settings().connector_secrets_json.strip()
    if raw_map:
        try:
            mapping = json.loads(raw_map)
        except json.JSONDecodeError:
            mapping = {}
        if isinstance(mapping, dict):
            candidate = mapping.get(secret_ref)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    raise ConnectorError(
        "CONNECTOR_SECRET_MISSING",
        f"Environment variable {secret_ref} is not set.",
    )


def has_secret(secret_ref: str | None) -> bool:
    try:
        resolve_secret(secret_ref)
    except ConnectorError:
        return False
    return True


def find_secret_keys(value: Any, prefix: str = "") -> list[str]:
    """Return dotted paths of config keys that look like credentials."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            lowered = str(key).lower()
            if any(marker in lowered for marker in SECRET_KEY_MARKERS):
                found.append(path)
            else:
                found.extend(find_secret_keys(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(find_secret_keys(item, f"{prefix}[{index}]"))
    return found

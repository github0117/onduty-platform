"""Generic read-only HTTP JSON business-system connector."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import httpx

from ticket_agent.connectors.base import (
    ConnectorError,
    HealthCheck,
    resolve_secret,
)
from ticket_agent.connectors.models import ExternalConnector


class HTTPJSONReadAdapter:
    """Read-only GET adapter; writes stay with the MCP tool-governance path."""

    def __init__(self, connector: ExternalConnector) -> None:
        self.connector = connector
        config = connector.config_json or {}
        self.base_url = str(config.get("base_url", "")).strip()
        if not self.base_url:
            raise ConnectorError(
                "HTTP_CONFIG_INVALID",
                "config.base_url is required for http_json connectors.",
            )
        self.path = str(config.get("path", "")).strip()
        self.health_path = str(config.get("health_path", "")).strip()
        self.timeout_seconds = float(config.get("timeout_seconds", 20))
        self.headers = {
            str(key): str(value)
            for key, value in config.get("headers", {}).items()
        }
        self.auth_header = str(config.get("auth_header", "Authorization"))
        self.auth_scheme = str(config.get("auth_scheme", "Bearer"))
        self.extra_params = {
            str(key): str(value)
            for key, value in config.get("params", {}).items()
        }

    def _headers(self) -> dict[str, str]:
        headers = dict(self.headers)
        if isinstance(self.connector.secret_ref, str) and self.connector.secret_ref:
            token = resolve_secret(self.connector.secret_ref)
            value = f"{self.auth_scheme} {token}".strip()
            headers[self.auth_header] = value
        return headers

    def health(self) -> HealthCheck:
        url = urljoin(self.base_url.rstrip("/") + "/", self.health_path.lstrip("/"))
        try:
            response = httpx.get(
                url,
                headers=self._headers(),
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise ConnectorError(
                "HTTP_HEALTH_FAILED",
                f"{type(exc).__name__}: {exc}",
                retryable=True,
            ) from exc
        if response.status_code >= 400:
            # A health endpoint answering 4xx is not healthy: the usual causes
            # are a wrong path, expired credentials or a disabled upstream.
            raise ConnectorError(
                "HTTP_HEALTH_FAILED",
                f"Health endpoint returned {response.status_code}.",
                retryable=response.status_code >= 500
                or response.status_code == 429,
            )
        return HealthCheck(
            healthy=True,
            detail=f"Health endpoint returned {response.status_code}.",
            metadata={
                "status_code": response.status_code,
                "url": url,
            },
        )

    def query(self, params: dict[str, str]) -> dict[str, Any]:
        url = urljoin(self.base_url.rstrip("/") + "/", self.path.lstrip("/"))
        merged = {**self.extra_params, **params}
        try:
            response = httpx.get(
                url,
                params=merged,
                headers=self._headers(),
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise ConnectorError(
                "HTTP_QUERY_FAILED",
                f"{type(exc).__name__}: {exc}",
                retryable=True,
            ) from exc
        if response.status_code in {429} or response.status_code >= 500:
            raise ConnectorError(
                "HTTP_QUERY_FAILED",
                f"Query returned {response.status_code}.",
                retryable=True,
            )
        if response.status_code >= 400:
            raise ConnectorError(
                "HTTP_QUERY_REJECTED",
                f"Query returned {response.status_code}.",
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise ConnectorError(
                "HTTP_QUERY_NOT_JSON",
                "Query response is not valid JSON.",
            ) from exc
        return {
            "status_code": response.status_code,
            "data": data,
        }

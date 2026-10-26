import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from ticket_agent.shared.settings import Settings, get_settings


class PinduoduoGatewayError(Exception):
    pass


@dataclass(frozen=True)
class PinduoduoGatewayResponse:
    api_type: str
    payload: dict[str, Any]


class PinduoduoGatewayClient:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.settings = settings
        self._client = client or httpx.Client(
            timeout=settings.pinduoduo_api_timeout_seconds
        )
        self._clock = clock or time.time

    @property
    def app_configured(self) -> bool:
        return bool(
            self.settings.pinduoduo_client_id
            and self.settings.pinduoduo_client_secret
        )

    @property
    def merchant_authorized(self) -> bool:
        return bool(self.settings.pinduoduo_access_token)

    @property
    def configured(self) -> bool:
        return self.app_configured

    def test_connection(self) -> PinduoduoGatewayResponse:
        return self.call("pdd.time.get")

    def call(
        self,
        api_type: str,
        *,
        business_params: dict[str, object] | None = None,
    ) -> PinduoduoGatewayResponse:
        if not self.app_configured:
            raise PinduoduoGatewayError(
                "Pinduoduo client_id and client_secret are not configured"
            )
        params: dict[str, str] = {
            "type": api_type,
            "client_id": self.settings.pinduoduo_client_id,
            "timestamp": str(int(self._clock())),
            "data_type": "JSON",
            "version": "V1",
        }
        if self.settings.pinduoduo_access_token:
            params["access_token"] = self.settings.pinduoduo_access_token
        for key, value in (business_params or {}).items():
            params[key] = str(value)
        params["sign"] = sign_pinduoduo_params(
            params,
            self.settings.pinduoduo_client_secret,
        )
        try:
            response = self._client.post(
                self.settings.pinduoduo_api_base_url,
                data=params,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PinduoduoGatewayError(
                f"Pinduoduo gateway request failed: {type(exc).__name__}"
            ) from exc
        if not isinstance(payload, dict):
            raise PinduoduoGatewayError(
                "Pinduoduo gateway returned a non-object response"
            )
        if "error_response" in payload:
            raise PinduoduoGatewayError(
                f"Pinduoduo gateway error: {payload['error_response']}"
            )
        return PinduoduoGatewayResponse(api_type=api_type, payload=payload)


def sign_pinduoduo_params(params: dict[str, str], secret: str) -> str:
    unsigned = {
        key: value
        for key, value in params.items()
        if key != "sign" and value != ""
    }
    joined = "".join(
        f"{key}{unsigned[key]}" for key in sorted(unsigned)
    )
    return hashlib.md5(
        f"{secret}{joined}{secret}".encode()
    ).hexdigest().upper()


def get_pinduoduo_gateway(
    settings: Settings | None = None,
) -> PinduoduoGatewayClient:
    return PinduoduoGatewayClient(settings or get_settings())

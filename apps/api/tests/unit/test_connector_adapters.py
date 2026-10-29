import email as email_lib
from email.message import EmailMessage
from uuid import UUID

import httpx
import pytest

from ticket_agent.connectors.base import (
    ConnectorError,
    OutboundEnvelope,
    find_secret_keys,
    resolve_secret,
)
from ticket_agent.connectors.email_adapter import (
    build_outbound_message,
    extract_body,
    message_to_envelope,
    thread_id_for,
)
from ticket_agent.connectors.http_json_adapter import HTTPJSONReadAdapter
from ticket_agent.connectors.inbound import poll_correlation_id
from ticket_agent.connectors.models import ExternalConnector
from ticket_agent.connectors.service import compute_signature, verify_signature
from ticket_agent.shared.errors import ApiProblem


def _connector(**overrides: object) -> ExternalConnector:
    values: dict[str, object] = {
        "business_unit_id": "bu_demo",
        "connector_key": "mail",
        "name": "Mail",
        "connector_type": "email",
        "direction": "BIDIRECTIONAL",
        "config_json": {
            "imap_host": "127.0.0.1",
            "from_address": "support@example.com",
            "username": "support@example.com",
        },
        "field_mapping_json": {},
        "auto_reply_enabled": True,
    }
    values.update(overrides)
    return ExternalConnector(**values)  # type: ignore[arg-type]


def _raw_email(
    *,
    message_id: str = "<reply-1@example.com>",
    references: str = "<root-1@example.com>",
    sender: str = "buyer@example.com",
    subject: str = "订单什么时候发货",
    body: str = "请问订单什么时候发货？",
) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "support@example.com"
    message["Subject"] = subject
    message["Message-ID"] = message_id
    if references:
        message["References"] = references
    message.set_content(body)
    return message.as_bytes()


def test_message_parsing_uses_references_as_thread_root() -> None:
    message = email_lib.message_from_bytes(_raw_email())

    envelope = message_to_envelope(message, folder="INBOX", uid="7")

    assert envelope.external_message_id == "<reply-1@example.com>"
    assert envelope.external_conversation_id == "<root-1@example.com>"
    assert envelope.external_user_id == "buyer@example.com"
    assert envelope.subject == "订单什么时候发货"
    assert envelope.content == "请问订单什么时候发货？"


def test_thread_id_falls_back_to_own_message_id() -> None:
    message = email_lib.message_from_bytes(_raw_email(references=""))

    assert (
        thread_id_for(message, folder="INBOX", uid="8")
        == "<reply-1@example.com>"
    )


def test_html_only_body_is_stripped() -> None:
    message = EmailMessage()
    message["From"] = "buyer@example.com"
    message.set_content("<p>你好<br/>需要帮助</p>", subtype="html")

    assert extract_body(message) == "你好\n需要帮助"


def test_outbound_message_carries_thread_headers() -> None:
    built = build_outbound_message(
        from_address="support@example.com",
        message=OutboundEnvelope(
            recipient="buyer@example.com",
            subject="Re: 订单什么时候发货",
            content="今天发出",
            message_id="<external-outbound.1@connector.local>",
            in_reply_to="<reply-1@example.com>",
            thread_id="<root-1@example.com>",
        ),
    )

    assert built["To"] == "buyer@example.com"
    assert built["Message-ID"] == "<external-outbound.1@connector.local>"
    assert built["In-Reply-To"] == "<reply-1@example.com>"
    assert built["References"] == "<root-1@example.com>"


def test_signature_round_trip_and_rejection() -> None:
    connector = _connector(secret_ref="TEST_CONNECTOR_SECRET")
    body = b'{"message_id":"m1"}'
    signature = compute_signature("s3cret", body)

    assert signature.startswith("sha256=")
    with pytest.raises(ApiProblem) as missing:
        verify_signature(connector, body=body, signature=None)
    assert missing.value.code == "CONNECTOR_SIGNATURE_MISSING"
    with pytest.raises(ApiProblem) as missing_secret:
        verify_signature(connector, body=body, signature=signature)
    assert missing_secret.value.code == "CONNECTOR_SIGNATURE_SECRET_MISSING"


def test_signature_secret_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_CONNECTOR_SECRET", "s3cret")
    connector = _connector(secret_ref="TEST_CONNECTOR_SECRET")
    body = b"payload"

    verify_signature(
        connector,
        body=body,
        signature=compute_signature("s3cret", body),
    )
    with pytest.raises(ApiProblem) as invalid:
        verify_signature(
            connector,
            body=body,
            signature=compute_signature("other", body),
        )
    assert invalid.value.code == "CONNECTOR_SIGNATURE_INVALID"


def test_resolve_secret_reports_missing_configuration() -> None:
    with pytest.raises(ConnectorError) as exc:
        resolve_secret(None)
    assert exc.value.code == "CONNECTOR_SECRET_NOT_CONFIGURED"
    with pytest.raises(ConnectorError) as missing:
        resolve_secret("DEFINITELY_NOT_SET_CONNECTOR_SECRET")
    assert missing.value.code == "CONNECTOR_SECRET_MISSING"


def test_secret_keys_are_detected_recursively() -> None:
    found = find_secret_keys(
        {
            "imap_host": "mail",
            "auth": {"password": "x", "nested": [{"token": "y"}]},
            "header_env": "SAFE_NAME",
        }
    )

    assert found == ["auth.password", "auth.nested[0].token"]


def _http_connector(**config: object) -> ExternalConnector:
    base: dict[str, object] = {"base_url": "http://orders.local"}
    base.update(config)
    return _connector(
        connector_type="http_json",
        direction="INBOUND",
        config_json=base,
        secret_ref=None,
    )


def test_http_adapter_returns_json_and_maps_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        del kwargs
        request = httpx.Request("GET", url)
        return httpx.Response(
            200,
            json={"order_id": "O-1"},
            request=request,
        )

    monkeypatch.setattr(
        "ticket_agent.connectors.http_json_adapter.httpx.get",
        fake_get,
    )
    result = HTTPJSONReadAdapter(_http_connector()).query({"order_id": "O-1"})

    assert result == {"status_code": 200, "data": {"order_id": "O-1"}}


def test_http_health_rejects_4xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        del kwargs
        return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr(
        "ticket_agent.connectors.http_json_adapter.httpx.get",
        fake_get,
    )
    with pytest.raises(ConnectorError) as exc:
        HTTPJSONReadAdapter(
            _http_connector(health_path="/missing")
        ).health()
    assert exc.value.code == "HTTP_HEALTH_FAILED"
    assert exc.value.retryable is False


def test_http_adapter_marks_rate_limit_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        del kwargs
        return httpx.Response(429, request=httpx.Request("GET", url))

    monkeypatch.setattr(
        "ticket_agent.connectors.http_json_adapter.httpx.get",
        fake_get,
    )
    with pytest.raises(ConnectorError) as exc:
        HTTPJSONReadAdapter(_http_connector()).query({})
    assert exc.value.retryable is True

    def fake_404(url: str, **kwargs: object) -> httpx.Response:
        del kwargs
        return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr(
        "ticket_agent.connectors.http_json_adapter.httpx.get",
        fake_404,
    )
    with pytest.raises(ConnectorError) as rejected:
        HTTPJSONReadAdapter(_http_connector()).query({})
    assert rejected.value.retryable is False


def test_poll_correlation_id_stays_within_audit_column() -> None:
    connector_id = UUID("cc0375e9-ada1-4cf2-b714-482a674784c8")
    long_message_id = "<" + "very-long-" * 20 + "message@example.com>"

    value = poll_correlation_id(connector_id, long_message_id)

    assert value == poll_correlation_id(connector_id, long_message_id)
    assert len(value) <= 64
    assert value.startswith("connector-poll-")
    assert poll_correlation_id(connector_id, "other") != value

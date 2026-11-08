import base64
import hashlib
import hmac
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location(
    "alert_relay", ROOT / "infra/alert-relay/relay.py"
)
assert SPEC is not None and SPEC.loader is not None
relay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(relay)

PAYLOAD = {
    "status": "firing",
    "groupLabels": {"alertname": "TicketSemanticUnsupportedClaims", "business_unit": "bu_demo"},
    "alerts": [
        {
            "labels": {
                "alertname": "TicketSemanticUnsupportedClaims",
                "severity": "critical",
                "business_unit": "bu_demo",
            },
            "annotations": {
                "summary": "881 unsupported claims",
                "description": "semantic verification found unsupported claims",
            },
            "startsAt": "2026-11-08T09:00:00Z",
        }
    ],
}


def test_firing_text_contains_alert_context() -> None:
    text = relay.format_alert_text(PAYLOAD)
    assert text.startswith("[FIRING] 1 alert(s)")
    assert "business_unit=bu_demo" in text
    assert "[critical] TicketSemanticUnsupportedClaims (bu_demo)" in text
    assert "881 unsupported claims" in text
    assert "started: 2026-11-08T09:00:00Z" in text


def test_resolved_text_uses_resolved_status() -> None:
    text = relay.format_alert_text({"status": "resolved", "alerts": []})
    assert text.startswith("[RESOLVED] 0 alert(s)")


def test_feishu_signature_matches_documented_algorithm() -> None:
    timestamp = 1731056400
    secret = "test-secret"
    string_to_sign = f"{timestamp}\n{secret}"
    expected = base64.b64encode(
        hmac.new(string_to_sign.encode("utf-8"), b"", digestmod=hashlib.sha256).digest()
    ).decode("utf-8")
    assert relay.feishu_signature(timestamp, secret) == expected


def test_payload_signs_only_when_secret_is_configured() -> None:
    unsigned = relay.build_feishu_payload(PAYLOAD, "", timestamp=1731056400)
    assert unsigned["msg_type"] == "text"
    assert "sign" not in unsigned
    assert "timestamp" not in unsigned

    signed = relay.build_feishu_payload(PAYLOAD, "test-secret", timestamp=1731056400)
    assert signed["timestamp"] == "1731056400"
    assert signed["sign"] == relay.feishu_signature(1731056400, "test-secret")


def test_long_text_is_truncated() -> None:
    payload = {
        "status": "firing",
        "alerts": [
            {
                "labels": {"alertname": "NoisyAlert"},
                "annotations": {"summary": "x" * relay.MAX_TEXT_CHARS},
            }
        ],
    }
    text = relay.format_alert_text(payload)
    assert len(text) <= relay.MAX_TEXT_CHARS
    assert text.endswith("...")

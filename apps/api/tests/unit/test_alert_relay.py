import base64
import hashlib
import hmac
import importlib.util
import json
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
    unsigned = relay.build_feishu_payload(PAYLOAD, "", timestamp=1731056400, message_format="text")
    assert unsigned["msg_type"] == "text"
    assert "sign" not in unsigned
    assert "timestamp" not in unsigned

    signed = relay.build_feishu_payload(
        PAYLOAD, "test-secret", timestamp=1731056400, message_format="text"
    )
    assert signed["timestamp"] == "1731056400"
    assert signed["sign"] == relay.feishu_signature(1731056400, "test-secret")


def test_default_payload_is_an_interactive_card() -> None:
    body = relay.build_feishu_payload(PAYLOAD, "", message_format="card")
    assert body["msg_type"] == "interactive"
    card = body["card"]
    assert card["header"]["template"] == "red"
    assert card["header"]["title"]["content"] == "告警触发 · 1 条 · bu_demo"

    joined = json.dumps(card, ensure_ascii=False)
    assert "TicketSemanticUnsupportedClaims" in joined
    assert "critical" in joined
    assert "881 unsupported claims" in joined


def test_card_header_color_follows_status_and_severity() -> None:
    critical = {"status": "firing", "alerts": [{"labels": {"severity": "critical"}}]}
    warning = {"status": "firing", "alerts": [{"labels": {"severity": "warning"}}]}
    resolved = {"status": "resolved", "alerts": [{"labels": {"severity": "critical"}}]}
    unknown = {"status": "firing", "alerts": [{"labels": {"severity": "page"}}]}

    assert relay.build_feishu_card(critical)["header"]["template"] == "red"
    assert relay.build_feishu_card(warning)["header"]["template"] == "orange"
    assert relay.build_feishu_card(resolved)["header"]["template"] == "green"
    assert relay.build_feishu_card(unknown)["header"]["template"] == "grey"


def test_card_limits_rendered_alerts_and_notes_the_rest() -> None:
    payload = {
        "status": "firing",
        "alerts": [
            {"labels": {"alertname": f"Alert{i}", "severity": "warning"}} for i in range(12)
        ],
    }
    card = relay.build_feishu_card(payload)
    joined = json.dumps(card, ensure_ascii=False)
    assert joined.count('"tag": "hr"') == relay.MAX_CARD_ALERTS
    assert "另有 4 条告警未展示" in joined


def test_card_truncates_long_description() -> None:
    payload = {
        "status": "firing",
        "alerts": [
            {
                "labels": {"alertname": "NoisyAlert"},
                "annotations": {"description": "y" * (relay.MAX_CARD_FIELD_CHARS + 50)},
            }
        ],
    }
    card = relay.build_feishu_card(payload)
    notes = [e for e in card["elements"] if e["tag"] == "note"]
    assert any(len(n["elements"][0]["content"]) == relay.MAX_CARD_FIELD_CHARS for n in notes)


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


def _load_selftest():
    spec = importlib.util.spec_from_file_location(
        "alert_relay_selftest", ROOT / "infra/alert-relay/selftest.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_selftest_requires_webhook_url(monkeypatch) -> None:
    selftest = _load_selftest()
    monkeypatch.delenv("FEISHU_WEBHOOK_URL", raising=False)
    assert selftest.main() == 2


def test_selftest_reports_feishu_rejection(monkeypatch, capsys) -> None:
    selftest = _load_selftest()
    monkeypatch.setenv("FEISHU_WEBHOOK_URL", "http://127.0.0.1:9/hook")
    monkeypatch.setattr(selftest, "load_relay", lambda: relay)
    monkeypatch.setattr(relay, "post_to_feishu", lambda url, body: (False, "feishu code=19021"))
    assert selftest.main() == 1
    assert "failed" in capsys.readouterr().err


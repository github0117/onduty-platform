"""Alertmanager -> Feishu custom bot relay.

Alertmanager posts its native webhook payload here; this service converts it
into a Feishu interactive card (default) or plain text message, and forwards
it to FEISHU_WEBHOOK_URL with the optional signature.

Environment:
  FEISHU_WEBHOOK_URL      Feishu custom bot webhook URL (required to start).
  FEISHU_WEBHOOK_SECRET   Optional signing secret; enables timestamp+sign.
  FEISHU_MESSAGE_FORMAT   "card" (default) or "text".
  ALERT_RELAY_PORT        Listen port, default 8080.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

MAX_BODY_BYTES = 1_000_000
MAX_TEXT_CHARS = 4_000
MAX_CARD_ALERTS = 8
MAX_CARD_FIELD_CHARS = 300
REQUEST_TIMEOUT_SECONDS = 5.0

FEISHU_WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK_URL", "")
FEISHU_WEBHOOK_SECRET = os.environ.get("FEISHU_WEBHOOK_SECRET", "")
FEISHU_MESSAGE_FORMAT = os.environ.get("FEISHU_MESSAGE_FORMAT", "card")
LISTEN_PORT = int(os.environ.get("ALERT_RELAY_PORT", "8080"))

# Feishu card header colors: red / orange / green / blue / grey.
SEVERITY_COLORS = {
    "critical": "red",
    "warning": "orange",
    "info": "blue",
}

LOGGER = logging.getLogger("alert-relay")


def feishu_signature(timestamp: int, secret: str) -> str:
    """Return the base64 HMAC-SHA256 signature Feishu expects."""
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        string_to_sign.encode("utf-8"), b"", digestmod=hashlib.sha256
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def format_alert_text(payload: dict[str, Any]) -> str:
    status = str(payload.get("status", "unknown")).upper()
    alerts = payload.get("alerts") or []
    groups = payload.get("groupLabels") or {}

    header = f"[{status}] {len(alerts)} alert(s)"
    if groups:
        labels = ", ".join(f"{key}={value}" for key, value in sorted(groups.items()))
        header += f" ({labels})"
    lines = [header]

    for alert in alerts:
        labels = alert.get("labels") or {}
        annotations = alert.get("annotations") or {}
        name = labels.get("alertname", "unknown")
        severity = labels.get("severity", "unknown")
        business_unit = labels.get("business_unit")
        line = f"- [{severity}] {name}"
        if business_unit:
            line += f" ({business_unit})"
        summary = annotations.get("summary")
        if summary:
            line += f": {summary}"
        lines.append(line)
        description = annotations.get("description")
        if description:
            lines.append(f"  {description}")
        starts_at = alert.get("startsAt")
        if starts_at:
            lines.append(f"  started: {starts_at}")

    text = "\n".join(lines)
    if len(text) > MAX_TEXT_CHARS:
        text = text[: MAX_TEXT_CHARS - 3] + "..."
    return text


def _truncate(value: str, limit: int = MAX_CARD_FIELD_CHARS) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def card_header_color(status: str, alerts: list[dict[str, Any]]) -> str:
    """Resolved is always green; otherwise the most severe level wins."""
    if status == "resolved":
        return "green"
    severities = {
        str((alert.get("labels") or {}).get("severity", "")).lower() for alert in alerts
    }
    for severity in ("critical", "warning", "info"):
        if severity in severities:
            return SEVERITY_COLORS[severity]
    return "grey"


def build_feishu_card(payload: dict[str, Any]) -> dict[str, Any]:
    status = str(payload.get("status", "unknown")).lower()
    alerts = list(payload.get("alerts") or [])
    groups = payload.get("groupLabels") or {}

    prefix = {"firing": "告警触发", "resolved": "告警恢复"}.get(status, status)
    title = f"{prefix} · {len(alerts)} 条"
    business_unit = groups.get("business_unit")
    if business_unit:
        title += f" · {business_unit}"

    elements: list[dict[str, Any]] = []
    if groups.get("alertname"):
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**告警规则**：{groups['alertname']}",
                },
            }
        )

    for alert in alerts[:MAX_CARD_ALERTS]:
        labels = alert.get("labels") or {}
        annotations = alert.get("annotations") or {}
        name = labels.get("alertname", "unknown")
        severity = labels.get("severity", "unknown")
        alert_unit = labels.get("business_unit")

        meta = [f"级别：**{severity}**"]
        if alert_unit:
            meta.append(f"业务线：**{alert_unit}**")
        lines = [f"**{name}**", "　".join(meta)]
        summary = annotations.get("summary")
        if summary:
            lines.append(_truncate(str(summary)))
        elements.append(
            {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}
        )

        description = annotations.get("description")
        if description:
            elements.append(
                {
                    "tag": "note",
                    "elements": [
                        {"tag": "plain_text", "content": _truncate(str(description))}
                    ],
                }
            )
        starts_at = alert.get("startsAt")
        if starts_at:
            elements.append(
                {
                    "tag": "note",
                    "elements": [
                        {"tag": "plain_text", "content": f"开始时间：{starts_at}"}
                    ],
                }
            )
        elements.append({"tag": "hr"})

    if len(alerts) > MAX_CARD_ALERTS:
        hidden = len(alerts) - MAX_CARD_ALERTS
        elements.append(
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": f"另有 {hidden} 条告警未展示，请到 Alertmanager 查看。",
                    }
                ],
            }
        )

    elements.append(
        {
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": "OnDuty 数字员工平台 · Prometheus Alertmanager",
                }
            ],
        }
    )

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": card_header_color(status, alerts),
            "title": {"tag": "plain_text", "content": title},
        },
        "elements": elements,
    }


def build_feishu_payload(
    payload: dict[str, Any],
    secret: str,
    timestamp: int | None = None,
    message_format: str | None = None,
) -> dict[str, Any]:
    fmt = (message_format or FEISHU_MESSAGE_FORMAT or "card").strip().lower()
    if fmt == "text":
        body: dict[str, Any] = {
            "msg_type": "text",
            "content": {"text": format_alert_text(payload)},
        }
    else:
        body = {"msg_type": "interactive", "card": build_feishu_card(payload)}

    if secret:
        ts = timestamp if timestamp is not None else int(time.time())
        body["timestamp"] = str(ts)
        body["sign"] = feishu_signature(ts, secret)
    return body


def post_to_feishu(url: str, body: dict[str, Any]) -> tuple[bool, str]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return False, f"http {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", type(exc).__name__)
        return False, f"transport error: {reason}"

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        return False, f"non-json response: {raw[:120]}"

    code = result.get("code")
    if code not in (0, None):
        return False, f"feishu code={code} msg={result.get('msg')}"
    return True, raw


class AlertRelayHandler(BaseHTTPRequestHandler):
    server_version = "alert-relay"

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/alerts":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0 or length > MAX_BODY_BYTES:
            self.send_error(400)
            return

        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self.send_error(400)
            return

        ok, detail = post_to_feishu(
            FEISHU_WEBHOOK_URL,
            build_feishu_payload(payload, FEISHU_WEBHOOK_SECRET),
        )
        if not ok:
            LOGGER.error("feishu delivery failed: %s", detail)
            self.send_response(502)
            self.end_headers()
            self.wfile.write(b"feishu delivery failed")
            return

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_GET(self) -> None:  # noqa: N802
        if urlparse(self.path).path == "/healthz":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return
        self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        LOGGER.info("%s - %s", self.address_string(), format % args)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parsed = urlparse(FEISHU_WEBHOOK_URL)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        LOGGER.error("FEISHU_WEBHOOK_URL is missing or invalid; refusing to start")
        return 1
    if parsed.scheme == "http":
        LOGGER.warning("FEISHU_WEBHOOK_URL uses http; only acceptable for local mocks")
    if not FEISHU_WEBHOOK_SECRET:
        LOGGER.warning("FEISHU_WEBHOOK_SECRET is empty; Feishu signature is disabled")

    server = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), AlertRelayHandler)
    LOGGER.info("alert relay listening on :%s", LISTEN_PORT)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())

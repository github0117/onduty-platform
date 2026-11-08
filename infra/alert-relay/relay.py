"""Alertmanager -> Feishu custom bot relay.

Alertmanager posts its native webhook payload here; this service converts it
into the Feishu text-message shape (and optional signature) and forwards it
to FEISHU_WEBHOOK_URL.

Environment:
  FEISHU_WEBHOOK_URL      Feishu custom bot webhook URL (required to start).
  FEISHU_WEBHOOK_SECRET   Optional signing secret; enables timestamp+sign.
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
REQUEST_TIMEOUT_SECONDS = 5.0

FEISHU_WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK_URL", "")
FEISHU_WEBHOOK_SECRET = os.environ.get("FEISHU_WEBHOOK_SECRET", "")
LISTEN_PORT = int(os.environ.get("ALERT_RELAY_PORT", "8080"))

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


def build_feishu_payload(
    payload: dict[str, Any],
    secret: str,
    timestamp: int | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "msg_type": "text",
        "content": {"text": format_alert_text(payload)},
    }
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

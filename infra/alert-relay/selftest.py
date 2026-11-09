"""Send one sample alert through the configured Feishu webhook.

Used for real bot onboarding: it reuses relay.py's payload builder and
signature so a success here means the same message Alertmanager sends will
be accepted by the Feishu group.

Environment:
  FEISHU_WEBHOOK_URL      Feishu custom bot webhook URL (required).
  FEISHU_WEBHOOK_SECRET   Optional signing secret.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

SAMPLE_PAYLOAD: dict[str, Any] = {
    "status": "firing",
    "groupLabels": {
        "alertname": "FeishuIntegrationTest",
        "business_unit": "bu_demo",
    },
    "alerts": [
        {
            "labels": {
                "alertname": "FeishuIntegrationTest",
                "severity": "warning",
                "business_unit": "bu_demo",
            },
            "annotations": {
                "summary": "OnDuty 飞书告警链路自检",
                "description": "看到这条消息说明 relay -> 飞书群链路已打通，可忽略。",
            },
            "startsAt": "2026-11-09T00:00:00Z",
        }
    ],
}


def load_relay() -> Any:
    path = Path(__file__).with_name("relay.py")
    spec = importlib.util.spec_from_file_location("alert_relay", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load relay from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    url = os.environ.get("FEISHU_WEBHOOK_URL", "")
    secret = os.environ.get("FEISHU_WEBHOOK_SECRET", "")
    if not url:
        print("FEISHU_WEBHOOK_URL is required", file=sys.stderr)
        return 2

    relay = load_relay()
    body = relay.build_feishu_payload(SAMPLE_PAYLOAD, secret)
    print(f"format: {body['msg_type']}")
    if body["msg_type"] == "interactive":
        card = body["card"]
        header = card["header"]
        print(f"title: {header['title']['content']} (color={header['template']})")
        for element in card["elements"]:
            text = element.get("text") or {}
            print(f"- <{element['tag']}> {text.get('content', '')}".rstrip())
    else:
        print(body["content"]["text"])
    print(f"signature: {'enabled' if secret else 'disabled'}")

    ok, detail = relay.post_to_feishu(url, body)
    if ok:
        print(f"result: ok ({detail})")
        return 0
    print(f"result: failed ({detail})", file=sys.stderr)
    if "sign" in detail.lower() or "19021" in detail:
        print(
            "hint: 飞书拒绝签名，检查 FEISHU_WEBHOOK_SECRET 是否与机器人后台一致",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())

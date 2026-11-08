from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]


def test_alertmanager_routes_to_webhook_without_inline_url() -> None:
    config = yaml.safe_load(
        (ROOT / "infra/alertmanager/alertmanager.yml").read_text(encoding="utf-8")
    )

    receivers = {receiver["name"] for receiver in config["receivers"]}
    default_receiver = config["route"]["receiver"]
    assert default_receiver in receivers

    webhook = next(
        receiver for receiver in config["receivers"] if receiver["name"] == default_receiver
    )
    webhook_config = webhook["webhook_configs"][0]
    assert webhook_config["url_file"] == "/tmp/alert_webhook_url"
    assert "url" not in webhook_config
    assert webhook_config["send_resolved"] is True

    severities = {route["matchers"][0] for route in config["route"]["routes"]}
    assert 'severity="critical"' in severities
    assert 'severity="warning"' in severities


def test_prometheus_sends_alerts_to_alertmanager() -> None:
    config = yaml.safe_load(
        (ROOT / "infra/prometheus/prometheus.yml").read_text(encoding="utf-8")
    )

    targets = [
        target
        for manager in config["alerting"]["alertmanagers"]
        for static in manager["static_configs"]
        for target in static["targets"]
    ]
    assert "alertmanager:9093" in targets


def test_compose_wires_alertmanager_into_observability_profile() -> None:
    compose = yaml.safe_load(
        (ROOT / "infra/compose/docker-compose.yml").read_text(encoding="utf-8")
    )

    service = compose["services"]["alertmanager"]
    assert service["profiles"] == ["observability"]
    assert "ALERT_WEBHOOK_URL" in service["environment"]
    assert service["volumes"][0].startswith("../alertmanager/alertmanager.yml")
    assert "alertmanager_data" in compose["volumes"]

"""Adapter factory: the only place connector_type becomes concrete code."""

from ticket_agent.connectors.base import (
    ConnectorError,
    InboundChannelAdapter,
    OutboundChannelAdapter,
    ReadOnlyAdapter,
)
from ticket_agent.connectors.email_adapter import EmailConnectorAdapter
from ticket_agent.connectors.http_json_adapter import HTTPJSONReadAdapter
from ticket_agent.connectors.models import ExternalConnector


def build_inbound_adapter(connector: ExternalConnector) -> InboundChannelAdapter:
    if connector.connector_type != "email":
        raise ConnectorError(
            "CONNECTOR_INBOUND_UNSUPPORTED",
            f"{connector.connector_type} connectors cannot poll inbound messages.",
        )
    return EmailConnectorAdapter(connector)


def build_outbound_adapter(connector: ExternalConnector) -> OutboundChannelAdapter:
    if connector.connector_type != "email":
        raise ConnectorError(
            "CONNECTOR_OUTBOUND_UNSUPPORTED",
            f"{connector.connector_type} connectors are read-only.",
        )
    return EmailConnectorAdapter(connector)


def build_read_adapter(connector: ExternalConnector) -> ReadOnlyAdapter:
    if connector.connector_type != "http_json":
        raise ConnectorError(
            "CONNECTOR_QUERY_UNSUPPORTED",
            f"{connector.connector_type} connectors do not support queries.",
        )
    return HTTPJSONReadAdapter(connector)

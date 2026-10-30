import json
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from ticket_agent.connectors.base import (
    ConnectorError,
    DeliveryReceipt,
    InboundEnvelope,
    InboundFetch,
    OutboundEnvelope,
)
from ticket_agent.connectors.inbound import (
    ingest_envelope,
    poll_email_connectors_job,
)
from ticket_agent.connectors.models import (
    ExternalConnector,
    ExternalInboundMessage,
    ExternalOutboundMessage,
)
from ticket_agent.connectors.outbound import deliver_outbound_message
from ticket_agent.connectors.service import compute_signature
from ticket_agent.customer_service.models import (
    ConversationTurn,
    CustomerConversation,
    CustomerMessage,
)
from ticket_agent.customer_service.suggestions import (
    CustomerReplySuggestionService,
)
from ticket_agent.shared.db import SessionLocal
from ticket_agent.tickets.domain import TicketStatus, WorkflowState
from ticket_agent.tickets.drafts import DraftResult
from ticket_agent.tickets.models import Ticket

ADMIN = {"X-Actor-Id": "connector-admin", "X-Actor-Role": "admin"}
AGENT = {"X-Actor-Id": "connector-agent", "X-Actor-Role": "agent"}
OPERATOR = {
    "X-Actor-Id": "connector-operator",
    "X-Actor-Role": "knowledge_operator",
}
AUDITOR = {"X-Actor-Id": "connector-auditor", "X-Actor-Role": "auditor"}
MULTI_UNIT_ADMIN = {**ADMIN, "X-Business-Units": "bu_demo,bu_other"}
SECRET_ENV = "TEST_CONNECTOR_SECRET"
SECRET = "s3cret"
BUYER = "buyer@example.com"


def _email_config() -> dict[str, object]:
    return {
        "imap_host": "127.0.0.1",
        "imap_port": 9,
        "imap_ssl": False,
        "smtp_host": "127.0.0.1",
        "smtp_port": 9,
        "smtp_ssl": False,
        "username": "support@example.com",
        "from_address": "support@example.com",
        "timeout_seconds": 1,
    }


def _create_employee(
    client: TestClient,
    *,
    key: str = "connector_employee",
    business_unit_id: str = "bu_demo",
    headers: dict[str, str] = ADMIN,
) -> str:
    response = client.post(
        "/api/v1/digital-employees",
        headers=headers,
        json={
            "employee_key": key,
            "name": "连接器客服",
            "version": "1.0.0",
            "scenario_type": "customer_service_ticket",
            "workflow_key": "customer_service_ticket_v1",
            "business_unit_id": business_unit_id,
            "service_identity": f"digital_employee.{key}",
            "handoff_queue": "MANUAL_TRIAGE",
            "tool_allowlist": [
                "ticket.read",
                "knowledge.search",
                "draft.create",
            ],
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _create_entry(
    client: TestClient,
    *,
    code: str = "connector_entry",
    business_unit_id: str = "bu_demo",
    headers: dict[str, str] = ADMIN,
) -> str:
    response = client.post(
        "/api/v1/business-service-entries",
        headers=headers,
        json={
            "business_unit_id": business_unit_id,
            "code": code,
            "name": "邮件客服入口",
            "domain": "ecommerce",
            "channel": "email",
            "human_queue_id": "MANUAL_TRIAGE",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _create_connector(
    client: TestClient,
    *,
    key: str = "support_mail",
    business_unit_id: str = "bu_demo",
    direction: str = "BIDIRECTIONAL",
    secret_ref: str | None = SECRET_ENV,
    auto_reply: bool = True,
    headers: dict[str, str] = ADMIN,
    connector_type: str = "email",
    config: dict[str, object] | None = None,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/connectors",
        headers=headers,
        json={
            "business_unit_id": business_unit_id,
            "connector_key": key,
            "name": "客服邮件",
            "connector_type": connector_type,
            "direction": direction,
            "config": config or _email_config(),
            "secret_ref": secret_ref,
            "auto_reply_enabled": auto_reply,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _bind(
    client: TestClient,
    connector_id: str,
    entry_id: str,
    employee_id: str | None,
    *,
    headers: dict[str, str] = ADMIN,
) -> None:
    response = client.put(
        f"/api/v1/connectors/{connector_id}/bindings",
        headers=headers,
        json={
            "bindings": [
                {
                    "service_entry_id": entry_id,
                    "employee_id": employee_id,
                    "allowed_operations": ["knowledge.search"],
                }
            ]
        },
    )
    assert response.status_code == 200, response.text


def _webhook(
    client: TestClient,
    connector_id: str,
    payload: dict[str, object],
    *,
    signature: str | None = None,
) -> httpx.Response:
    body = json.dumps(payload, ensure_ascii=False).encode()
    headers = {"Content-Type": "application/json"}
    if signature is None:
        signature = compute_signature(SECRET, body)
    if signature:
        headers["X-Connector-Signature"] = signature
    return client.post(
        f"/api/v1/connectors/{connector_id}/inbound",
        content=body,
        headers=headers,
    )


def _payload(
    message_id: str = "<in-1@example.com>",
    thread_id: str = "<thread-1@example.com>",
    content: str = "请问我的订单什么时候发货？",
) -> dict[str, object]:
    return {
        "message_id": message_id,
        "thread_id": thread_id,
        "user_id": BUYER,
        "subject": "订单发货咨询",
        "content": content,
        "metadata": {"mailbox": "support"},
    }


def test_connector_permissions_credentials_and_versioning(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SECRET_ENV, SECRET)

    assert client.get("/api/v1/connectors", headers=AGENT).status_code == 403
    assert (
        client.get("/api/v1/connectors", headers=AUDITOR).status_code == 200
    )

    credentialed = client.post(
        "/api/v1/connectors",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "connector_key": "leaky_mail",
            "name": "带密码的邮件",
            "connector_type": "email",
            "direction": "BIDIRECTIONAL",
            "config": {**_email_config(), "password": "inline-secret"},
        },
    )
    assert credentialed.status_code == 422, credentialed.text

    created = _create_connector(client)
    assert created["secret_configured"] is True
    assert "password" not in created["config"]

    duplicate = client.post(
        "/api/v1/connectors",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "connector_key": "support_mail",
            "name": "重复邮件",
            "connector_type": "email",
            "direction": "BIDIRECTIONAL",
            "config": _email_config(),
            "secret_ref": SECRET_ENV,
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "CONNECTOR_KEY_EXISTS"

    cross_tenant = client.get(
        f"/api/v1/connectors/{created['id']}",
        headers={**ADMIN, "X-Business-Unit-Id": "bu_other"},
    )
    assert cross_tenant.status_code == 403

    viewer_write = client.patch(
        f"/api/v1/connectors/{created['id']}",
        headers=AUDITOR,
        json={"status": "DISABLED"},
    )
    assert viewer_write.status_code == 403

    disabled = client.patch(
        f"/api/v1/connectors/{created['id']}",
        headers=OPERATOR,
        json={"status": "DISABLED", "expected_version": 1},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["status"] == "DISABLED"
    assert disabled.json()["version"] == 2

    stale = client.patch(
        f"/api/v1/connectors/{created['id']}",
        headers=OPERATOR,
        json={"status": "ACTIVE", "expected_version": 1},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "CONNECTOR_VERSION_CONFLICT"


def test_connector_bindings_scope_and_replacement(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SECRET_ENV, SECRET)
    employee = _create_employee(client)
    entry = _create_entry(client)
    connector = _create_connector(client)
    other_employee = _create_employee(
        client,
        key="connector_employee_other",
        business_unit_id="bu_other",
        headers=MULTI_UNIT_ADMIN,
    )
    other_entry = _create_entry(
        client,
        code="connector_entry_other",
        business_unit_id="bu_other",
        headers=MULTI_UNIT_ADMIN,
    )
    del other_employee

    _bind(client, str(connector["id"]), entry, employee)
    bindings = client.get(
        f"/api/v1/connectors/{connector['id']}/bindings",
        headers=AUDITOR,
    )
    assert bindings.status_code == 200
    assert bindings.json()[0]["service_entry_name"] == "邮件客服入口"
    assert bindings.json()[0]["employee_name"] == "连接器客服"

    duplicate = client.put(
        f"/api/v1/connectors/{connector['id']}/bindings",
        headers=ADMIN,
        json={
            "bindings": [
                {"service_entry_id": entry},
                {"service_entry_id": entry},
            ]
        },
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["code"] == "CONNECTOR_BINDING_DUPLICATE"

    scope_mismatch = client.put(
        f"/api/v1/connectors/{connector['id']}/bindings",
        headers=ADMIN,
        json={"bindings": [{"service_entry_id": other_entry}]},
    )
    assert scope_mismatch.status_code == 422
    assert scope_mismatch.json()["code"] == "CONNECTOR_BINDING_SCOPE_MISMATCH"

    cleared = client.put(
        f"/api/v1/connectors/{connector['id']}/bindings",
        headers=ADMIN,
        json={"bindings": []},
    )
    assert cleared.status_code == 200
    assert cleared.json() == []


def test_webhook_signature_dedup_and_object_chain(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SECRET_ENV, SECRET)
    employee = _create_employee(client)
    entry = _create_entry(client)
    connector = _create_connector(client)
    _bind(client, str(connector["id"]), entry, employee)
    url = f"/api/v1/connectors/{connector['id']}/inbound"

    unsigned = client.post(
        url,
        content=json.dumps(_payload()).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert unsigned.status_code == 401
    assert unsigned.json()["code"] == "CONNECTOR_SIGNATURE_MISSING"

    wrong = _webhook(
        client,
        str(connector["id"]),
        _payload(),
        signature=compute_signature("other", b"{}"),
    )
    assert wrong.status_code == 401
    assert wrong.json()["code"] == "CONNECTOR_SIGNATURE_INVALID"

    accepted = _webhook(client, str(connector["id"]), _payload())
    assert accepted.status_code == 202, accepted.text
    inbound_id = accepted.json()["id"]

    messages = client.get(
        f"/api/v1/connectors/{connector['id']}/messages",
        headers=AUDITOR,
    ).json()
    assert messages["inbound"][0]["id"] == inbound_id
    assert messages["inbound"][0]["status"] == "PROCESSED"
    conversation_id = UUID(messages["inbound"][0]["conversation_id"])
    ticket_id = messages["inbound"][0]["ticket_id"]
    assert ticket_id is not None

    with SessionLocal() as session:
        conversation = session.get(CustomerConversation, conversation_id)
        assert conversation is not None
        assert str(conversation.external_connector_id) == connector["id"]
        assert conversation.external_thread_id == "<thread-1@example.com>"
        assert conversation.requester_ref == BUYER
        assert conversation.channel == "enterprise_email"
        assert conversation.service_entry_id == UUID(entry)
        buyer_messages = session.scalar(
            select(func.count())
            .select_from(CustomerMessage)
            .where(
                CustomerMessage.conversation_id == conversation_id,
                CustomerMessage.role == "BUYER",
            )
        )
        assert buyer_messages == 1
        ticket = session.get(Ticket, UUID(str(ticket_id)))
        assert ticket is not None
        assert ticket.business_unit_id == "bu_demo"

    duplicate = _webhook(client, str(connector["id"]), _payload())
    assert duplicate.status_code == 202
    assert duplicate.json()["id"] == inbound_id
    with SessionLocal() as session:
        inbound_count = session.scalar(
            select(func.count()).select_from(ExternalInboundMessage)
        )
        buyer_count = session.scalar(
            select(func.count())
            .select_from(CustomerMessage)
            .where(
                CustomerMessage.conversation_id == conversation_id,
                CustomerMessage.role == "BUYER",
            )
        )
    assert inbound_count == 1
    assert buyer_count == 1


def test_unbound_disabled_and_retry_path(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SECRET_ENV, SECRET)
    employee = _create_employee(client)
    entry = _create_entry(client)
    connector = _create_connector(client)

    unbound = _webhook(
        client,
        str(connector["id"]),
        _payload(content="你好", message_id="<unbound-1@example.com>"),
    )
    assert unbound.status_code == 422
    assert unbound.json()["code"] == "CONNECTOR_NOT_BOUND"
    with SessionLocal() as session:
        row = session.scalar(
            select(ExternalInboundMessage).where(
                ExternalInboundMessage.external_message_id
                == "<unbound-1@example.com>"
            )
        )
        assert row is not None
        assert row.status == "FAILED"
        assert row.error_code == "CONNECTOR_NOT_BOUND"
        failed_id = str(row.id)

    disabled = client.patch(
        f"/api/v1/connectors/{connector['id']}",
        headers=ADMIN,
        json={"status": "DISABLED"},
    )
    assert disabled.status_code == 200
    rejected = _webhook(
        client,
        str(connector["id"]),
        _payload(content="你好", message_id="<disabled-1@example.com>"),
    )
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "CONNECTOR_DISABLED"
    with SessionLocal() as session:
        row = session.scalar(
            select(ExternalInboundMessage).where(
                ExternalInboundMessage.external_message_id
                == "<disabled-1@example.com>"
            )
        )
        assert row is not None and row.status == "FAILED"

    assert (
        client.patch(
            f"/api/v1/connectors/{connector['id']}",
            headers=ADMIN,
            json={"status": "ACTIVE"},
        ).status_code
        == 200
    )
    _bind(client, str(connector["id"]), entry, employee)

    retried = client.post(
        f"/api/v1/connectors/{connector['id']}/inbound/{failed_id}/retry",
        headers=OPERATOR,
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "PROCESSED"
    assert retried.json()["conversation_id"] is not None

    unknown = client.post(
        f"/api/v1/connectors/{connector['id']}/inbound/"
        "00000000-0000-0000-0000-000000000000/retry",
        headers=OPERATOR,
    )
    assert unknown.status_code == 404


def test_small_talk_auto_reply_and_outbound_delivery(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SECRET_ENV, SECRET)
    employee = _create_employee(client)
    entry = _create_entry(client)
    connector = _create_connector(client)
    _bind(client, str(connector["id"]), entry, employee)

    accepted = _webhook(
        client,
        str(connector["id"]),
        _payload(
            content="你好",
            message_id="<smalltalk-1@example.com>",
            thread_id="<smalltalk-thread@example.com>",
        ),
    )
    assert accepted.status_code == 202, accepted.text

    messages = client.get(
        f"/api/v1/connectors/{connector['id']}/messages",
        headers=AUDITOR,
    ).json()
    assert messages["inbound"][0]["status"] == "PROCESSED"
    assert len(messages["outbound"]) == 1
    outbound = messages["outbound"][0]
    assert outbound["recipient"] == BUYER
    assert outbound["status"] == "QUEUED"
    assert outbound["subject"].startswith("Re: ")
    outbound_id = UUID(outbound["id"])

    delivered: list[OutboundEnvelope] = []

    class _FakeOutbound:
        def send(self, envelope: OutboundEnvelope) -> DeliveryReceipt:
            delivered.append(envelope)
            return DeliveryReceipt(external_message_id="<sent-1@example.com>")

    monkeypatch.setattr(
        "ticket_agent.connectors.outbound.build_outbound_adapter",
        lambda connector: _FakeOutbound(),
    )
    deliver_outbound_message(outbound_id)
    with SessionLocal() as session:
        row = session.get(ExternalOutboundMessage, outbound_id)
        assert row is not None
        assert row.status == "SENT"
        assert row.external_message_id == "<sent-1@example.com>"
        assert row.attempt_count == 1
    assert len(delivered) == 1
    envelope = delivered[0]
    assert envelope.recipient == BUYER
    assert envelope.thread_id == "<smalltalk-thread@example.com>"

    duplicate = _webhook(
        client,
        str(connector["id"]),
        _payload(
            content="你好",
            message_id="<smalltalk-1@example.com>",
            thread_id="<smalltalk-thread@example.com>",
        ),
    )
    assert duplicate.status_code == 202
    with SessionLocal() as session:
        outbound_count = session.scalar(
            select(func.count()).select_from(ExternalOutboundMessage)
        )
    assert outbound_count == 1


def test_auto_reply_requires_auto_send_gate(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An answer the gate held for review must not leave the connector."""
    monkeypatch.setenv(SECRET_ENV, SECRET)
    employee = _create_employee(client)
    entry = _create_entry(client)
    connector = _create_connector(client)
    _bind(client, str(connector["id"]), entry, employee)

    class _HeldGraph:
        def invoke(self, _state: dict[str, object]) -> dict[str, object]:
            return {
                "draft": DraftResult(
                    text="门禁维修需由设施团队处理。",
                    citations=[],
                    claims=[
                        {
                            "text": "门禁维修需由设施团队处理。",
                            "claim_type": "policy",
                            "cited_chunk_ids": [],
                            "verification_verdict": "supported",
                            "verification_confidence": 0.9,
                            "verification_reason": "test",
                            "verification_provider": "test",
                        }
                    ],
                    provider="stub",
                    model="stub-v1",
                    fallback_used=False,
                    grounding_status="GROUNDED",
                ),
                "skill": "stub-skill",
                "skill_definition": None,
                "skill_definition_version": None,
                "trace": ["stub"],
                "mcp_tool_calls": [],
            }

    monkeypatch.setattr(
        CustomerReplySuggestionService,
        "_build_graph",
        lambda self: _HeldGraph(),
    )

    accepted = _webhook(
        client,
        str(connector["id"]),
        _payload(
            content="办公室门禁失灵了怎么处理？",
            message_id="<gate-held@example.com>",
            thread_id="<gate-held-thread@example.com>",
        ),
    )
    assert accepted.status_code == 202, accepted.text

    messages = client.get(
        f"/api/v1/connectors/{connector['id']}/messages",
        headers=AUDITOR,
    ).json()
    assert messages["inbound"][0]["status"] == "PROCESSED"
    assert messages["outbound"] == []

    with SessionLocal() as session:
        turn = session.scalar(
            select(ConversationTurn).order_by(
                ConversationTurn.sequence.desc()
            )
        )
        assert turn is not None
        assert turn.gate_json is not None
        assert turn.gate_json["decision"] == "HUMAN_REVIEW"


def test_manual_reply_bridges_to_outbound(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SECRET_ENV, SECRET)
    employee = _create_employee(client)
    entry = _create_entry(client)
    connector = _create_connector(client)
    _bind(client, str(connector["id"]), entry, employee)

    accepted = _webhook(
        client,
        str(connector["id"]),
        _payload(message_id="<manual-1@example.com>"),
    )
    assert accepted.status_code == 202, accepted.text
    messages = client.get(
        f"/api/v1/connectors/{connector['id']}/messages",
        headers=AUDITOR,
    ).json()
    inbound = messages["inbound"][0]
    conversation_id = UUID(inbound["conversation_id"])
    with SessionLocal() as session:
        ticket = session.get(Ticket, UUID(str(inbound["ticket_id"])))
        assert ticket is not None
        ticket.workflow_state = WorkflowState.NEEDS_HUMAN
        ticket.status = TicketStatus.WAITING_HUMAN
        ticket.needs_human = True
        session.commit()

    conversation = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}",
        headers=AGENT,
    )
    assert conversation.status_code == 200, conversation.text
    takeover = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/takeover",
        headers=AGENT,
        json={"expected_version": conversation.json()["version"]},
    )
    assert takeover.status_code == 200, takeover.text

    replied = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/manual-replies",
        headers=AGENT,
        json={"content": "已为您核实订单，今天发出。", "resolve": True},
    )
    assert replied.status_code == 201, replied.text

    outbound = client.get(
        f"/api/v1/connectors/{connector['id']}/messages",
        headers=AUDITOR,
    ).json()["outbound"]
    assert len(outbound) == 1
    with SessionLocal() as session:
        row = session.get(ExternalOutboundMessage, UUID(outbound[0]["id"]))
        assert row is not None
        assert row.content == "已为您核实订单，今天发出。"
        assert row.idempotency_key.startswith("manual:")
        assert row.status == "QUEUED"


def test_health_and_read_only_query(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SECRET_ENV, SECRET)
    connector = _create_connector(client)
    unhealthy = client.post(
        f"/api/v1/connectors/{connector['id']}/health",
        headers=OPERATOR,
    )
    assert unhealthy.status_code == 200, unhealthy.text
    assert unhealthy.json()["healthy"] is False
    detail = client.get(
        f"/api/v1/connectors/{connector['id']}",
        headers=AUDITOR,
    ).json()
    assert detail["last_health_status"] == "UNHEALTHY"
    assert detail["last_health_error"]

    http_connector = _create_connector(
        client,
        key="order_center",
        connector_type="http_json",
        direction="INBOUND",
        secret_ref=None,
        config={
            "base_url": "http://orders.local",
            "path": "/orders",
            "health_path": "/healthz",
        },
    )

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        del kwargs
        if url.endswith("/healthz"):
            return httpx.Response(200, request=httpx.Request("GET", url))
        return httpx.Response(
            200,
            json={"order_id": "O-1"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(
        "ticket_agent.connectors.http_json_adapter.httpx.get",
        fake_get,
    )
    healthy = client.post(
        f"/api/v1/connectors/{http_connector['id']}/health",
        headers=OPERATOR,
    )
    assert healthy.status_code == 200
    assert healthy.json()["healthy"] is True

    queried = client.post(
        f"/api/v1/connectors/{http_connector['id']}/query",
        headers=AUDITOR,
        json={"params": {"order_id": "O-1"}},
    )
    assert queried.status_code == 200, queried.text
    assert queried.json()["data"] == {"order_id": "O-1"}

    email_query = client.post(
        f"/api/v1/connectors/{connector['id']}/query",
        headers=AUDITOR,
        json={"params": {}},
    )
    assert email_query.status_code == 409
    assert email_query.json()["code"] == "CONNECTOR_QUERY_UNSUPPORTED"


def test_concurrent_webhook_delivery_creates_one_row(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SECRET_ENV, SECRET)
    employee = _create_employee(client)
    entry = _create_entry(client)
    connector = _create_connector(client)
    _bind(client, str(connector["id"]), entry, employee)
    connector_id = UUID(str(connector["id"]))
    envelope = InboundEnvelope(
        external_message_id="<concurrent-1@example.com>",
        external_conversation_id="<concurrent-thread@example.com>",
        external_user_id=BUYER,
        subject="并发投递",
        content="你好",
    )

    def _ingest(_: int) -> bool:
        _, created = ingest_envelope(
            connector_id,
            envelope,
            correlation_id="concurrency-test",
        )
        return created

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(_ingest, range(5)))

    assert sum(results) == 1
    with SessionLocal() as session:
        rows = session.scalar(
            select(func.count()).select_from(ExternalInboundMessage)
        )
    assert rows == 1


def test_email_polling_deduplicates_and_survives_adapter_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SECRET_ENV, SECRET)
    employee = _create_employee(client)
    entry = _create_entry(client)
    connector = _create_connector(client)
    _bind(client, str(connector["id"]), entry, employee)

    fetched = InboundFetch(
        envelope=InboundEnvelope(
            external_message_id="<poll-1@example.com>",
            external_conversation_id="<poll-thread@example.com>",
            external_user_id=BUYER,
            subject="轮询邮件",
            content="你好",
        ),
        ack_token="INBOX|1",
    )
    acknowledged: list[str] = []

    class _FakeInbound:
        def fetch_inbound(self, *, limit: int) -> list[InboundFetch]:
            del limit
            return [fetched]

        def acknowledge(self, token: str) -> None:
            acknowledged.append(token)

        def health(self) -> object:
            raise AssertionError("not used")

    monkeypatch.setattr(
        "ticket_agent.connectors.inbound.build_inbound_adapter",
        lambda connector: _FakeInbound(),
    )
    assert poll_email_connectors_job() == 1
    assert acknowledged == ["INBOX|1"]
    assert poll_email_connectors_job() == 0
    assert acknowledged == ["INBOX|1", "INBOX|1"]

    class _BrokenInbound:
        def fetch_inbound(self, *, limit: int) -> list[InboundFetch]:
            del limit
            raise ConnectorError(
                "EMAIL_IMAP_CONNECT_FAILED",
                "boom",
                retryable=True,
            )

        def health(self) -> object:
            raise AssertionError("not used")

    monkeypatch.setattr(
        "ticket_agent.connectors.inbound.build_inbound_adapter",
        lambda connector: _BrokenInbound(),
    )
    assert poll_email_connectors_job() == 0

    with SessionLocal() as session:
        row = session.scalar(
            select(ExternalInboundMessage).where(
                ExternalInboundMessage.external_message_id
                == "<poll-1@example.com>"
            )
        )
        assert row is not None
        assert row.status == "PROCESSED"
        assert session.get(ExternalConnector, row.connector_id) is not None

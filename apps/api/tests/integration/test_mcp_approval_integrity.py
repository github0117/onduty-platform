from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ticket_agent.mcp_connectors.approvals import (
    McpToolApprovalService,
    _fingerprint,
)
from ticket_agent.mcp_connectors.models import McpToolApproval
from ticket_agent.shared.db import SessionLocal


def _approval(
    fingerprint: str,
    *,
    status: str = "PENDING",
    business_unit_id: str = "bu_demo",
    employee_id: UUID | None = None,
    connector_id: UUID | None = None,
) -> McpToolApproval:
    return McpToolApproval(
        business_unit_id=business_unit_id,
        employee_id=employee_id or uuid4(),
        connector_id=connector_id or uuid4(),
        tool_id="customer-orders.refund",
        connector_code="runtime-orders",
        tool_name="refund",
        request_fingerprint=fingerprint,
        status=status,
        requested_by="agent-1",
        request_correlation_id="corr-1",
    )


def _request_kwargs(
    *,
    employee_id: UUID,
    connector_id: UUID,
) -> dict[str, object]:
    return {
        "business_unit_id": "bu_demo",
        "employee_id": employee_id,
        "connector_id": connector_id,
        "connector_code": "runtime-orders",
        "tool_name": "refund",
        "tool_id": "customer-orders.refund",
        "arguments": {"order_id": "O-1"},
        "requested_by": "agent-1",
        "correlation_id": "corr-1",
        "ticket_id": None,
        "conversation_id": None,
        "reason": "refund requires approval",
        "request_tool_call_id": None,
        "required_role": "supervisor",
        "policy": {},
    }


def test_active_fingerprint_is_unique() -> None:
    fingerprint = "a" * 64
    with SessionLocal() as session:
        session.add(_approval(fingerprint))
        session.commit()

    with SessionLocal() as session:
        session.add(_approval(fingerprint))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_rejected_fingerprint_does_not_block_new_request() -> None:
    fingerprint = "b" * 64
    with SessionLocal() as session:
        session.add(_approval(fingerprint, status="REJECTED"))
        session.commit()

    with SessionLocal() as session:
        session.add(_approval(fingerprint))
        session.commit()
        count = session.scalar(
            select(func.count())
            .select_from(McpToolApproval)
            .where(McpToolApproval.request_fingerprint == fingerprint)
        )
        assert count == 2


def test_request_returns_winner_when_insert_races(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee_id = uuid4()
    connector_id = uuid4()
    fingerprint = _fingerprint(
        employee_id=employee_id,
        connector_id=connector_id,
        tool_id="customer-orders.refund",
        ticket_id=None,
        arguments={"order_id": "O-1"},
    )
    with SessionLocal() as session:
        winner = _approval(
            fingerprint,
            employee_id=employee_id,
            connector_id=connector_id,
        )
        session.add(winner)
        session.commit()
        winner_id = winner.id

    original = McpToolApprovalService._find_reusable
    calls = {"count": 0}

    def stale_first_lookup(
        service: McpToolApprovalService,
        *,
        fingerprint: str,
        business_unit_id: str,
    ) -> McpToolApproval | None:
        calls["count"] += 1
        if calls["count"] == 1:
            return None
        return original(
            service,
            fingerprint=fingerprint,
            business_unit_id=business_unit_id,
        )

    monkeypatch.setattr(
        McpToolApprovalService,
        "_find_reusable",
        stale_first_lookup,
    )

    with SessionLocal() as session:
        approval, reused = McpToolApprovalService(session).request(
            **_request_kwargs(  # type: ignore[arg-type]
                employee_id=employee_id,
                connector_id=connector_id,
            )
        )

        assert reused is True
        assert approval.id == winner_id
        assert calls["count"] == 2

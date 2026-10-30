"""Real-PostgreSQL proof that a turn's event log has one writer at a time.

The worker finishing a turn and a supervisor handing the conversation over
both append to the same ``conversation_turn_events`` row set. The sequence is
computed as ``max(sequence) + 1``, so two writers that read the same maximum
insert the same number: the second one fails on
``uq_conversation_turn_event_sequence`` and — when it is the worker — the turn
is left RUNNING until the lease reclaims it.

SQLite cannot show this (it has no row locks and serialises writes), which is
why this test only runs against a real PostgreSQL instance.
"""

import os
import threading
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from ticket_agent.customer_service.models import (
    ConversationTurn,
    ConversationTurnEvent,
    CustomerConversation,
    CustomerMessage,
)
from ticket_agent.customer_service.turn_events import record_turn_event

POSTGRES_URL = os.getenv("TEST_POSTGRES_URL")


@pytest.mark.skipif(not POSTGRES_URL, reason="TEST_POSTGRES_URL is not configured")
def test_second_writer_waits_for_the_first_instead_of_reusing_its_sequence() -> None:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    first_engine = create_engine(POSTGRES_URL)
    unit = f"bu_turn_event_seq_{uuid4().hex[:8]}"
    conversation_id = None
    try:
        with Session(engine) as setup:
            conversation = CustomerConversation(
                business_unit_id=unit,
                requester_ref="sequence-test",
            )
            setup.add(conversation)
            setup.flush()
            conversation_id = conversation.id
            message = CustomerMessage(
                conversation_id=conversation.id,
                sequence=1,
                role="BUYER",
                content="保温杯能保温多久？",
                created_by="sequence-test",
            )
            setup.add(message)
            setup.flush()
            setup.add(
                ConversationTurn(
                    conversation_id=conversation.id,
                    sequence=1,
                    status="RUNNING",
                    user_message_id=message.id,
                )
            )
            setup.commit()

        first = Session(engine)
        second = Session(first_engine)
        results: dict[str, object] = {}

        def append_second() -> None:
            try:
                turn = second.scalar(
                    select(ConversationTurn).where(
                        ConversationTurn.conversation_id == conversation_id
                    )
                )
                assert turn is not None
                event = record_turn_event(
                    second,
                    turn,
                    event_type="CONTEXT_ASSEMBLED",
                    actor_id="test.second",
                )
                second.commit()
                results["sequence"] = event.sequence
            except Exception as error:  # noqa: BLE001 - reported by the assertion
                results["error"] = error
            finally:
                second.close()

        try:
            turn = first.scalar(
                select(ConversationTurn).where(
                    ConversationTurn.conversation_id == conversation_id
                )
            )
            assert turn is not None
            record_turn_event(
                first,
                turn,
                event_type="TURN_STARTED",
                actor_id="test.first",
            )
            # The append is flushed but not committed: the row lock is held.
            thread = threading.Thread(target=append_second, daemon=True)
            thread.start()
            thread.join(timeout=0.5)
            assert thread.is_alive(), (
                "the second writer did not wait for the first one's turn lock"
            )
            first.commit()
            thread.join(timeout=15)
            assert not thread.is_alive(), "the second writer never finished"
        finally:
            first.close()

        assert "error" not in results, results.get("error")
        assert results["sequence"] == 2

        with Session(engine) as check:
            sequences = list(
                check.scalars(
                    select(ConversationTurnEvent.sequence)
                    .join(
                        ConversationTurn,
                        ConversationTurn.id == ConversationTurnEvent.turn_id,
                    )
                    .where(ConversationTurn.conversation_id == conversation_id)
                    .order_by(ConversationTurnEvent.sequence)
                )
            )
            assert sequences == [1, 2]
    finally:
        if conversation_id is not None:
            with Session(engine) as cleanup:
                cleanup.execute(
                    delete(ConversationTurnEvent).where(
                        ConversationTurnEvent.conversation_id == conversation_id
                    )
                )
                cleanup.execute(
                    delete(ConversationTurn).where(
                        ConversationTurn.conversation_id == conversation_id
                    )
                )
                cleanup.execute(
                    delete(CustomerMessage).where(
                        CustomerMessage.conversation_id == conversation_id
                    )
                )
                cleanup.execute(
                    delete(CustomerConversation).where(
                        CustomerConversation.id == conversation_id
                    )
                )
                cleanup.commit()
        engine.dispose()
        first_engine.dispose()

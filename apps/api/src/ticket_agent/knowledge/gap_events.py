"""Runtime knowledge-gap capture.

A buyer question the published knowledge could not answer is recorded as an
occurrence. Only when the same normalized question recurs
``knowledge_gap_repair_threshold`` times inside
``knowledge_gap_window_days`` does it open a repair task: one phrasing miss
should not create paperwork, and a real gap should not depend on a human
noticing it in the ticket list.

The recorder never commits on its own. It runs inside the turn transaction so
the occurrence and the turn either both land or neither does.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ticket_agent.knowledge.models import (
    KnowledgeGapOccurrence,
    KnowledgeRepairTask,
)
from ticket_agent.knowledge.repair_service import (
    KnowledgeRepairService,
    normalize_repair_query,
)
from ticket_agent.shared.settings import get_settings


def record_knowledge_gap(
    session: Session,
    *,
    business_unit_id: str,
    query: str,
    ticket_id: UUID | None = None,
    turn_id: UUID | None = None,
    created_by: str = "digital_employee.runtime",
) -> KnowledgeGapOccurrence | None:
    """Record one unanswerable question and open a repair task at threshold.

    Returns the occurrence, or ``None`` when the question is empty after
    normalization.
    """
    normalized = normalize_repair_query(query)
    if not normalized:
        return None
    occurrence = KnowledgeGapOccurrence(
        business_unit_id=business_unit_id,
        query=query[:4000],
        normalized_query=normalized,
        ticket_id=ticket_id,
        turn_id=turn_id,
    )
    session.add(occurrence)
    session.flush()

    settings = get_settings()
    threshold = max(settings.knowledge_gap_repair_threshold, 1)
    window_start = datetime.now(UTC) - timedelta(
        days=max(settings.knowledge_gap_window_days, 1)
    )
    matching = (
        KnowledgeGapOccurrence.business_unit_id == business_unit_id,
        KnowledgeGapOccurrence.normalized_query == normalized,
        KnowledgeGapOccurrence.created_at >= window_start,
    )
    occurrence_count = (
        session.scalar(
            select(func.count(KnowledgeGapOccurrence.id)).where(*matching)
        )
        or 0
    )
    if occurrence_count < threshold:
        return occurrence

    task: KnowledgeRepairTask = KnowledgeRepairService(
        session
    ).ensure_from_runtime_gap(
        business_unit_id=business_unit_id,
        normalized_query=normalized,
        created_by=created_by,
    )
    # Link every occurrence of this window, including ones recorded before the
    # task existed, so the task can show its evidence.
    session.execute(
        update(KnowledgeGapOccurrence)
        .where(*matching, KnowledgeGapOccurrence.repair_task_id.is_(None))
        .values(repair_task_id=task.id)
        .execution_options(synchronize_session=False)
    )
    # The bulk update bypasses the identity map; refresh so the caller sees
    # the link it just created.
    session.refresh(occurrence)
    return occurrence

from uuid import UUID

from ticket_agent.knowledge.reindex import KnowledgeReindexService
from ticket_agent.knowledge.service import KnowledgeService
from ticket_agent.shared.db import SessionLocal


def ingest_knowledge_version_job(version_id: UUID, correlation_id: str) -> None:
    with SessionLocal() as session:
        KnowledgeService(session).ingest_stored_version(
            version_id,
            correlation_id=correlation_id,
        )


def reindex_knowledge_job(job_id: UUID, correlation_id: str) -> None:
    with SessionLocal() as session:
        KnowledgeReindexService(session).run_job(
            job_id,
            correlation_id=correlation_id,
        )

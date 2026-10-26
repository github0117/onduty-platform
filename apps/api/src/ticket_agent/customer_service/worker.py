from ticket_agent.customer_service.service import CustomerConversationService
from ticket_agent.shared.db import SessionLocal


def auto_assign_customer_conversations_job(
    business_unit_id: str | None = None,
) -> int:
    with SessionLocal() as session:
        return CustomerConversationService(session).auto_assign(
            business_unit_id
        ).assigned_count

from uuid import UUID

from sqlalchemy.orm import Session

from ticket_agent.workflow.service import WorkflowService


class CustomerServiceTicketWorkflow:
    key = "customer_service_ticket_v1"

    def __init__(self, session: Session) -> None:
        self.session = session

    def process(self, ticket_id: UUID, correlation_id: str) -> None:
        WorkflowService(self.session).process(ticket_id, correlation_id)

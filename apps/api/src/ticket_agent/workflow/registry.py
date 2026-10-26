from uuid import UUID

from sqlalchemy.orm import Session

from ticket_agent.workflow.base import DigitalEmployeeWorkflow
from ticket_agent.workflow.hr_onboarding import HROnboardingWorkflow
from ticket_agent.workflow.service import WorkflowService


class CustomerServiceTicketWorkflow:
    key = "customer_service_ticket_v1"

    def __init__(self, session: Session) -> None:
        self.session = session

    def process(self, ticket_id: UUID, correlation_id: str) -> None:
        WorkflowService(self.session).process(ticket_id, correlation_id)


def get_workflow(session: Session, workflow_key: str) -> DigitalEmployeeWorkflow:
    workflows: dict[
        str,
        type[CustomerServiceTicketWorkflow] | type[HROnboardingWorkflow],
    ] = {
        CustomerServiceTicketWorkflow.key: CustomerServiceTicketWorkflow,
        HROnboardingWorkflow.key: HROnboardingWorkflow,
    }
    workflow_type = workflows.get(workflow_key)
    if workflow_type is None:
        raise ValueError(f"Unsupported workflow: {workflow_key}")
    return workflow_type(session)


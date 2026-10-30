from sqlalchemy.orm import Session

from ticket_agent.domains.registry import (
    DomainPackError,
    resolve_workflow_class,
)
from ticket_agent.workflow.base import DigitalEmployeeWorkflow
from ticket_agent.workflow.customer_service import CustomerServiceTicketWorkflow
from ticket_agent.workflow.hr_onboarding import HROnboardingWorkflow

__all__ = [
    "CustomerServiceTicketWorkflow",
    "HROnboardingWorkflow",
    "get_workflow",
]


def get_workflow(session: Session, workflow_key: str) -> DigitalEmployeeWorkflow:
    """Instantiate the workflow registered for ``workflow_key``.

    Registration lives in domain packs (built-in or ``DOMAIN_PACKS_DIR``), so
    this module no longer keeps its own key map.
    """
    try:
        workflow_type = resolve_workflow_class(workflow_key)
    except DomainPackError as exc:
        raise ValueError(f"Unsupported workflow: {workflow_key}") from exc
    return workflow_type(session)

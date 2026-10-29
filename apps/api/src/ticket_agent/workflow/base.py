from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session


class DigitalEmployeeWorkflow(Protocol):
    # Domain packs hand the registry a ``module:Class`` path; the registry
    # instantiates it with the current session.
    def __init__(self, session: Session) -> None: ...

    @property
    def key(self) -> str: ...

    def process(self, ticket_id: UUID, correlation_id: str) -> None: ...


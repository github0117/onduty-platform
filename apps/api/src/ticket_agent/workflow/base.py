from typing import Protocol
from uuid import UUID


class DigitalEmployeeWorkflow(Protocol):
    @property
    def key(self) -> str: ...

    def process(self, ticket_id: UUID, correlation_id: str) -> None: ...


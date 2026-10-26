from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from ticket_agent.identity.dependencies import get_principal
from ticket_agent.identity.models import Principal
from ticket_agent.shared.db import get_db

DbSession = Annotated[Session, Depends(get_db)]
Actor = Annotated[Principal, Depends(get_principal)]


def correlation_id(request: Request) -> str:
    return str(request.state.correlation_id)


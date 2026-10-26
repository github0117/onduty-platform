from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiProblem(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        title: str,
        detail: str,
        retryable: bool = False,
        context: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.title = title
        self.detail = detail
        self.retryable = retryable
        self.context = context or {}
        self.headers = headers or {}


async def api_problem_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiProblem):
        raise exc
    payload = {
        "type": f"https://api.example.com/problems/{exc.code.lower().replace('_', '-')}",
        "title": exc.title,
        "status": exc.status_code,
        "detail": exc.detail,
        "code": exc.code,
        "correlation_id": getattr(request.state, "correlation_id", None),
        "retryable": exc.retryable,
        "context": exc.context,
    }
    return JSONResponse(
        status_code=exc.status_code,
        content=payload,
        headers=exc.headers,
    )


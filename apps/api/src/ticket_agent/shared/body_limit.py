"""Reject oversized request bodies before endpoints buffer them.

Upload and JSON endpoints read the whole body through FastAPI's ``Request``.
The limit therefore sits at the middleware boundary so that a client cannot
force the API to allocate an arbitrary amount of memory, including when the
body is streamed without a ``Content-Length`` header.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response

from ticket_agent.shared.errors import ApiProblem, api_problem_handler
from ticket_agent.shared.settings import get_settings

RequestHandler = Callable[[Request], Awaitable[Response]]

_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})


async def enforce_request_body_limit(
    request: Request,
    call_next: RequestHandler,
) -> Response:
    """Enforce ``MAX_REQUEST_BYTES`` for every request that can carry a body."""

    if request.method not in _BODY_METHODS:
        return await call_next(request)

    max_bytes = get_settings().max_request_bytes
    declared = _declared_length(request)
    if declared is not None and declared > max_bytes:
        return await _payload_too_large(request, max_bytes)

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > max_bytes:
            return await _payload_too_large(request, max_bytes)

    # BaseHTTPMiddleware replays the cached body to downstream middleware.
    request._body = bytes(body)
    return await call_next(request)


def _declared_length(request: Request) -> int | None:
    raw = request.headers.get("content-length")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


async def _payload_too_large(request: Request, max_bytes: int) -> Response:
    return await api_problem_handler(
        request,
        ApiProblem(
            status_code=413,
            code="PAYLOAD_TOO_LARGE",
            title="Request body is too large",
            detail="请求内容超过允许的大小限制。",
            context={"max_request_bytes": max_bytes},
        ),
    )

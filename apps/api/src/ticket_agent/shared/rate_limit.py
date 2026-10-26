"""Rate limiting for expensive, model or tool backed endpoints.

The limiter is keyed by authenticated actor and business unit, so one tenant
cannot exhaust another tenant's budget. Redis is used when configured; when it
is unavailable the limiter falls back to a per-process sliding window so that
an infrastructure outage does not take write traffic down with it.
"""

from __future__ import annotations

import hashlib
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Annotated, Any

from fastapi import Depends
from redis import Redis
from redis.exceptions import RedisError

from ticket_agent.identity.dependencies import get_principal
from ticket_agent.identity.models import Principal
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import Settings, get_settings

_MEMORY_LOCK = Lock()
_MEMORY_HITS: dict[str, deque[float]] = {}
_MEMORY_PRUNE_THRESHOLD = 4096

_REDIS_LOCK = Lock()
_REDIS_CLIENT: Redis | None = None
_REDIS_URL: str | None = None
_REDIS_RETRY_AT = 0.0
_REDIS_RETRY_SECONDS = 30.0

_METRIC_LOCK = Lock()
_REJECTIONS = 0


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int


def check_rate_limit(
    *,
    identity: str,
    limit: int,
    window_seconds: int,
    settings: Settings,
    now: float | None = None,
) -> RateLimitDecision:
    """Return whether the identity may perform one more request in this window."""

    if limit <= 0:
        return RateLimitDecision(allowed=True, remaining=0, retry_after_seconds=0)

    current = time.time() if now is None else now
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    key = f"{settings.rate_limit_key_prefix}:{digest}"

    if settings.rate_limit_backend == "redis":
        client = _redis_client(settings, current)
        if client is not None:
            try:
                return _check_redis(client, key, limit, window_seconds, current)
            except RedisError:
                _mark_redis_unavailable(current)
    return _check_memory(key, limit, window_seconds, current)


def rate_limited() -> Callable[..., None]:
    """Build a FastAPI dependency enforcing the shared request budget."""

    def enforce(
        principal: Annotated[Principal, Depends(get_principal)],
    ) -> None:
        settings = get_settings()
        if not settings.rate_limit_enabled:
            return
        decision = check_rate_limit(
            identity=_identity(principal),
            limit=settings.rate_limit_requests_per_minute,
            window_seconds=settings.rate_limit_window_seconds,
            settings=settings,
        )
        if decision.allowed:
            return
        record_rate_limit_rejection()
        raise ApiProblem(
            status_code=429,
            code="RATE_LIMITED",
            title="Too many requests",
            detail="请求过于频繁，请稍后再试。",
            retryable=True,
            context={"retry_after_seconds": decision.retry_after_seconds},
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )

    return enforce


def reset_rate_limits() -> None:
    """Clear in-process counters. Intended for tests and demo resets."""

    global _REDIS_CLIENT, _REDIS_URL, _REDIS_RETRY_AT
    with _MEMORY_LOCK:
        _MEMORY_HITS.clear()
    with _REDIS_LOCK:
        _REDIS_CLIENT = None
        _REDIS_URL = None
        _REDIS_RETRY_AT = 0.0


def record_rate_limit_rejection() -> None:
    """Count a rejected request for the Prometheus exporter."""

    global _REJECTIONS
    with _METRIC_LOCK:
        _REJECTIONS += 1


def rate_limit_rejection_total() -> int:
    """Return rejected requests since process start (or the last test reset)."""

    with _METRIC_LOCK:
        return _REJECTIONS


def reset_rate_limit_metrics() -> None:
    """Reset the rejection counter. Intended for tests."""

    global _REJECTIONS
    with _METRIC_LOCK:
        _REJECTIONS = 0


def _identity(principal: Principal) -> str:
    return f"{principal.actor_id}|{principal.primary_business_unit_id or '-'}"


def _check_redis(
    client: Redis,
    key: str,
    limit: int,
    window_seconds: int,
    now: float,
) -> RateLimitDecision:
    bucket = int(now // window_seconds)
    bucket_key = f"{key}:{bucket}"
    pipe = client.pipeline(transaction=True)
    pipe.incr(bucket_key)
    pipe.expire(bucket_key, max(window_seconds * 2, 2))
    values: list[Any] = pipe.execute()
    count = int(values[0])
    if count <= limit:
        return RateLimitDecision(
            allowed=True,
            remaining=limit - count,
            retry_after_seconds=0,
        )
    retry_after = max(1, int(window_seconds - (now % window_seconds)))
    return RateLimitDecision(
        allowed=False,
        remaining=0,
        retry_after_seconds=retry_after,
    )


def _check_memory(
    key: str,
    limit: int,
    window_seconds: int,
    now: float,
) -> RateLimitDecision:
    cutoff = now - window_seconds
    with _MEMORY_LOCK:
        if len(_MEMORY_HITS) > _MEMORY_PRUNE_THRESHOLD:
            _prune_memory(cutoff)
        hits = _MEMORY_HITS.setdefault(key, deque())
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= limit:
            retry_after = max(1, int(hits[0] + window_seconds - now) + 1)
            return RateLimitDecision(
                allowed=False,
                remaining=0,
                retry_after_seconds=retry_after,
            )
        hits.append(now)
        return RateLimitDecision(
            allowed=True,
            remaining=limit - len(hits),
            retry_after_seconds=0,
        )


def _prune_memory(cutoff: float) -> None:
    stale = [key for key, hits in _MEMORY_HITS.items() if not hits or hits[-1] <= cutoff]
    for key in stale:
        del _MEMORY_HITS[key]


def _redis_client(settings: Settings, now: float) -> Redis | None:
    global _REDIS_CLIENT, _REDIS_URL
    if now < _REDIS_RETRY_AT:
        return None
    with _REDIS_LOCK:
        if _REDIS_CLIENT is None or settings.redis_url != _REDIS_URL:
            _REDIS_CLIENT = Redis.from_url(
                settings.redis_url,
                socket_connect_timeout=0.2,
                socket_timeout=0.2,
                decode_responses=True,
            )
            _REDIS_URL = settings.redis_url
        return _REDIS_CLIENT


def _mark_redis_unavailable(now: float) -> None:
    global _REDIS_RETRY_AT
    with _REDIS_LOCK:
        _REDIS_RETRY_AT = now + _REDIS_RETRY_SECONDS

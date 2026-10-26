import pytest
from redis.exceptions import RedisError

from ticket_agent.shared.rate_limit import check_rate_limit, reset_rate_limits
from ticket_agent.shared.settings import Settings


@pytest.fixture(autouse=True)
def clear_limits() -> None:
    reset_rate_limits()


def _settings(**overrides: object) -> Settings:
    return Settings(
        rate_limit_enabled=True,
        rate_limit_backend="memory",
        rate_limit_window_seconds=60,
        rate_limit_requests_per_minute=2,
    ).model_copy(update=overrides)


def test_memory_limiter_allows_limit_then_blocks() -> None:
    settings = _settings()

    first = check_rate_limit(
        identity="agent|bu_demo",
        limit=2,
        window_seconds=60,
        settings=settings,
        now=1000.0,
    )
    second = check_rate_limit(
        identity="agent|bu_demo",
        limit=2,
        window_seconds=60,
        settings=settings,
        now=1000.5,
    )
    blocked = check_rate_limit(
        identity="agent|bu_demo",
        limit=2,
        window_seconds=60,
        settings=settings,
        now=1001.0,
    )

    assert first.allowed is True
    assert first.remaining == 1
    assert second.allowed is True
    assert second.remaining == 0
    assert blocked.allowed is False
    assert blocked.retry_after_seconds == 60


def test_memory_limiter_releases_expired_hits() -> None:
    settings = _settings()

    for moment in (1000.0, 1001.0):
        assert check_rate_limit(
            identity="agent|bu_demo",
            limit=2,
            window_seconds=60,
            settings=settings,
            now=moment,
        ).allowed

    assert not check_rate_limit(
        identity="agent|bu_demo",
        limit=2,
        window_seconds=60,
        settings=settings,
        now=1002.0,
    ).allowed

    assert check_rate_limit(
        identity="agent|bu_demo",
        limit=2,
        window_seconds=60,
        settings=settings,
        now=1062.0,
    ).allowed


def test_rate_limits_are_scoped_by_identity() -> None:
    settings = _settings()

    assert check_rate_limit(
        identity="alpha|bu_alpha",
        limit=1,
        window_seconds=60,
        settings=settings,
        now=2000.0,
    ).allowed
    assert not check_rate_limit(
        identity="alpha|bu_alpha",
        limit=1,
        window_seconds=60,
        settings=settings,
        now=2000.1,
    ).allowed
    assert check_rate_limit(
        identity="beta|bu_beta",
        limit=1,
        window_seconds=60,
        settings=settings,
        now=2000.2,
    ).allowed


def test_redis_failure_falls_back_to_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(rate_limit_backend="redis")

    class DownRedis:
        def pipeline(self, transaction: bool = True) -> None:
            raise RedisError("redis is down")

    monkeypatch.setattr(
        "ticket_agent.shared.rate_limit._redis_client",
        lambda _settings, _now: DownRedis(),
    )

    allowed = check_rate_limit(
        identity="agent|bu_demo",
        limit=1,
        window_seconds=60,
        settings=settings,
        now=3000.0,
    )
    blocked = check_rate_limit(
        identity="agent|bu_demo",
        limit=1,
        window_seconds=60,
        settings=settings,
        now=3000.5,
    )

    assert allowed.allowed is True
    assert blocked.allowed is False

"""
Tests that a dependency replaced by a fallback says so in the log.

Three of the four already did -- the cache, the task queue and the mailer
each name theirs on the way past. The rate limiter did not, and it is the
one whose silence costs most: ``MemoryRateLimiter`` keeps its window in
the process, so a deployment running four gunicorn workers enforces the
configured limit four times over, once per worker. Nothing said so, and
``/health`` cannot say it either -- the limiter is reachable and
enforcing, just not the way the operator asked for.

The cache's line is here for a different reason: it named a profile
rather than a state, reading ``Using in-memory cache (development).``
whichever profile was running, so a production deployment with Redis
switched off found the word ``development`` in its own log.

What each line claims is checked here as well, not only that a line was
written: a warning about windows that are not shared is worth nothing if
the windows turn out to be shared.
"""

import pytest

from link_shortener.infrastructure.di.components.cache import CacheComponent
from link_shortener.infrastructure.di.components.rate_limiter import (
    RateLimiterComponent,
)
from link_shortener.infrastructure.rate_limit.memory_rate_limiter import (
    MemoryRateLimiter,
)


class RecordingLogger:
    """A logger that keeps what it was told, by level."""

    def __init__(self):
        self.lines = []

    def _record(self, level):
        def write(message, **fields):
            self.lines.append((level, message))
        return write

    def __getattr__(self, level):
        if level in ("debug", "info", "warning", "error", "critical"):
            return self._record(level)
        raise AttributeError(level)

    def said(self):
        """Every message, whatever its level."""
        return " | ".join(message for _level, message in self.lines)


@pytest.fixture
def logger():
    return RecordingLogger()


class TestTheRateLimiterWithoutRedis:

    def test_the_fallback_is_announced(self, logger):
        component = RateLimiterComponent(
            redis_enabled=False, redis_url="", logger=logger
        )

        limiter = component.get_rate_limiter()

        assert isinstance(limiter, MemoryRateLimiter)
        assert "in-memory rate limiter" in logger.said()

    def test_the_announcement_names_what_it_costs(self, logger):
        """A line saying only "using the in-memory limiter" tells an
        operator nothing they can act on. What matters is that the limit
        is now enforced per worker."""
        RateLimiterComponent(
            redis_enabled=False, redis_url="", logger=logger
        ).get_rate_limiter()

        assert "worker" in logger.said()

    def test_each_limiter_holds_its_own_window(self):
        """The claim the warning makes, measured rather than asserted.

        Two limiters stand for two workers: one key, one limit, and the
        second still allows what the first has already refused.
        """
        first, second = MemoryRateLimiter(), MemoryRateLimiter()
        key, limit, period = "ip:198.51.100.7", 3, 60

        for _ in range(limit):
            assert first.is_allowed(key, limit, period) is True

        assert first.is_allowed(key, limit, period) is False
        assert second.is_allowed(key, limit, period) is True

    def test_nothing_is_announced_when_redis_is_there(self, logger):
        """The line belongs to the fallback, not to every startup."""
        component = RateLimiterComponent(
            redis_enabled=True, redis_url="redis://localhost:6379/0",
            logger=logger,
        )

        component.get_rate_limiter()

        assert "in-memory rate limiter" not in logger.said()


class TestTheCacheWithoutRedis:

    def test_the_line_describes_the_state_not_the_profile(self, logger):
        """``development`` in a production log is a line to distrust."""
        component = CacheComponent(
            cache_enabled=True, redis_enabled=False, redis_url="",
            link_prefix="test", logger=logger, link_ttl=60, stats_ttl=60,
            connect_timeout=1, socket_timeout=1, retry_interval=1,
            secret_key="k" * 64,
        )

        component.get_cache()

        said = logger.said()
        assert "in-memory cache" in said
        assert "development" not in said

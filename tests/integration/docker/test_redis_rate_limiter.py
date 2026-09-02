"""The Redis limiter refuses, against a real Redis.

The sliding window is a Lua script evaluated on the server, so nothing about
it is exercised by a mock. A mutation run making the script always allow left
the whole suite green: the unit tests cover the degradation path -- what
happens when Redis is gone -- and never the enforcement path, which is the
one the protection actually consists of.

Atomicity is the reason the logic lives in a script rather than in Python, so
it is checked here too: concurrent callers must not be able to overshoot the
limit between a read and a write.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from link_shortener.infrastructure.rate_limit.redis_rate_limiter import (
    RedisRateLimiter,
)


@pytest.fixture
def limiter(app, redis_client):
    """A limiter on the real Redis, sharing one namespace across the file.

    The isolation is the ``key`` fixture below, not the namespace: this
    passes no prefix, so every test in this file writes under the
    limiter's default one. A reader who took the namespace for the
    isolation would drop the fresh key and find the tests interfering.

    Depends on ``app`` only so that the schema exists: the autouse cleanup
    fixture truncates tables after every test, and without it this file
    could not be run on its own.
    """
    return RedisRateLimiter(redis_client)


@pytest.fixture
def key():
    """A key no other test shares."""
    return f"ratelimit-test-{uuid.uuid4()}"


class TestTheWindowIsEnforced:
    """Allowed up to the limit, refused past it."""

    def test_requests_up_to_the_limit_are_allowed(self, limiter, key):
        decisions = [limiter.check(key, limit=3, period=60) for _ in range(3)]

        assert all(d.allowed for d in decisions), decisions

    def test_the_next_request_is_refused(self, limiter, key):
        """The assertion whose absence let the script be gutted unnoticed."""
        for _ in range(3):
            limiter.check(key, limit=3, period=60)

        assert limiter.check(key, limit=3, period=60).allowed is False

    def test_remaining_counts_down_to_zero(self, limiter, key):
        """The number the client is handed has to mean something."""
        first = limiter.check(key, limit=3, period=60)
        assert first.remaining == 2

        limiter.check(key, limit=3, period=60)
        third = limiter.check(key, limit=3, period=60)

        assert third.remaining == 0

    def test_keys_are_counted_separately(self, limiter):
        """One caller's exhaustion must not refuse another."""
        noisy, quiet = f"noisy-{uuid.uuid4()}", f"quiet-{uuid.uuid4()}"
        for _ in range(3):
            limiter.check(noisy, limit=3, period=60)

        assert limiter.check(quiet, limit=3, period=60).allowed is True

    def test_the_limiter_reports_itself_as_enforcing(self, limiter, key):
        """`/health` reads this; it must not claim protection it lost."""
        limiter.check(key, limit=3, period=60)

        assert limiter.is_enforcing() is True


class TestTheWindowHoldsUnderConcurrency:
    """The script is atomic; the limit is not a suggestion."""

    def test_parallel_callers_cannot_overshoot(self, limiter, key):
        """Read-then-write in Python would let several past at once.

        Twenty threads against a limit of five: exactly five may pass. A
        larger number means the check and the increment were separable, which
        is what the Lua script exists to prevent.
        """
        limit, callers = 5, 20

        with ThreadPoolExecutor(max_workers=callers) as pool:
            decisions = list(
                pool.map(
                    lambda _: limiter.check(key, limit=limit, period=60),
                    range(callers),
                )
            )

        allowed = sum(1 for d in decisions if d.allowed)
        assert allowed == limit, (
            f"{allowed} callers were allowed past a limit of {limit}"
        )

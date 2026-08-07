"""The in-memory limiter has to actually refuse.

Nothing asserted that it does. A mutation run making ``is_allowed`` return
``True`` unconditionally left the whole suite green: the limiter was
constructed and consulted in other tests, but no test ever pushed it past
its limit and checked the answer.
"""

import time

import pytest

from link_shortener.infrastructure.rate_limit.memory_rate_limiter import (
    MemoryRateLimiter,
)


@pytest.fixture
def limiter():
    """A limiter with no history."""
    return MemoryRateLimiter()


class TestTheLimitIsEnforced:
    """Allowed up to the limit, refused past it."""

    def test_requests_up_to_the_limit_are_allowed(self, limiter):
        assert all(
            limiter.is_allowed("client-a", limit=3, period=60) for _ in range(3)
        )

    def test_the_next_request_is_refused(self, limiter):
        """The assertion the mutation run showed nothing was making."""
        for _ in range(3):
            limiter.is_allowed("client-b", limit=3, period=60)

        assert limiter.is_allowed("client-b", limit=3, period=60) is False

    def test_a_limit_of_zero_refuses_everything(self, limiter):
        """An off-by-one here would quietly grant one free request."""
        assert limiter.is_allowed("client-c", limit=0, period=60) is False

    def test_clients_are_counted_separately(self, limiter):
        """One client's exhaustion must not refuse another.

        The live service has the opposite problem for a different reason --
        an empty TRUSTED_PROXIES makes every caller look like one address --
        but that is configuration, not this class.
        """
        for _ in range(3):
            limiter.is_allowed("noisy", limit=3, period=60)

        assert limiter.is_allowed("quiet", limit=3, period=60) is True

    def test_the_window_expires(self, limiter):
        """A limiter that never forgets is a limiter that locks people out."""
        assert limiter.is_allowed("client-d", limit=1, period=1) is True
        assert limiter.is_allowed("client-d", limit=1, period=1) is False

        time.sleep(1.1)

        assert limiter.is_allowed("client-d", limit=1, period=1) is True


class TestRemainingIsReported:
    """The header the client reads has to mean something."""

    def test_it_counts_down(self, limiter):
        assert limiter.get_remaining("client-e", limit=3, period=60) == 3

        limiter.is_allowed("client-e", limit=3, period=60)

        assert limiter.get_remaining("client-e", limit=3, period=60) == 2

    def test_it_stops_at_zero(self, limiter):
        """A negative remaining count would render as a nonsense header."""
        for _ in range(5):
            limiter.is_allowed("client-f", limit=2, period=60)

        assert limiter.get_remaining("client-f", limit=2, period=60) == 0

"""
"No cache configured" was said about a cache serving redirects out of memory.

``is_configured`` answers "is there a cache service to watch". It was also
read as "is anything being cached", and those are two questions:
``NullCache`` keeps nothing and ``InMemoryLinkCache`` keeps entries in this
process, and both answered ``False``.

Measured on a live run of this service with ``REDIS_ENABLED=false`` and
``CACHE_ENABLED=true``: ``/health`` answered ``"cache": "disabled"`` while
the same process logged four ``Redirect cache hit`` lines in the same
seconds. The difference is not academic -- an in-process cache is not
shared, so a link deleted through one worker goes on redirecting through
the others until its TTL runs out, and the operator reading "disabled" has
been told there is no cache to suspect.

Held on the snapshot rather than on a rendered page, because that is where
the verdict is decided now: four surfaces used to decide it themselves,
each in its own words, and the two facts added most recently had to be
written into all four.
"""

import pytest

from link_shortener.application.ports.health_check import HealthSnapshot
from link_shortener.infrastructure.cache.memory_cache import InMemoryLinkCache
from link_shortener.infrastructure.cache.null_cache import NullCache


def _a_memory_cache():
    """The in-process cache, built the way the container builds it."""
    return InMemoryLinkCache(prefix="test", link_ttl=300, stats_ttl=60)


def snapshot(**overrides):
    """A healthy snapshot, with what a test is about named."""
    fields = {
        "database": True,
        "cache": True,
        "cache_configured": False,
        "task_queue": True,
        "rate_limiter": True,
    }
    fields.update(overrides)
    return HealthSnapshot(**fields)


class TestTheCachesAnswerTheTwoQuestionsApart:
    """Each cache says what it is, rather than a report guessing."""

    @pytest.mark.parametrize(
        "cache, configured, stores",
        [
            (NullCache(), False, False),
            (_a_memory_cache(), False, True),
        ],
    )
    def test_what_each_one_reports(self, cache, configured, stores):
        assert cache.is_configured() is configured
        assert cache.stores_entries() is stores

    def test_the_in_memory_cache_really_does_keep_what_it_says(self):
        """
        The claim ``stores_entries`` makes, measured rather than asserted.

        A method returning ``True`` proves nothing about the object; what
        proves it is the entry coming back out.
        """
        from link_shortener.domain.value_objects.short_code import ShortCode

        cache = _a_memory_cache()
        cache.save_redirect(ShortCode("keepme"), "https://example.com/kept")

        assert cache.get_redirect(ShortCode("keepme")) is not None
        assert cache.stores_entries() is True


class TestTheVerdictSaysWhichOfTheThreeItIs:
    """
    Three states, because there are three, and one word covered two.
    """

    def test_a_cache_keeping_entries_in_this_process(self):
        assert snapshot(cache_stores=True).component_states()["cache"] == (
            "in_process"
        )

    def test_a_cache_keeping_nothing(self):
        assert snapshot(cache_stores=False).component_states()["cache"] == (
            "disabled"
        )

    def test_a_cache_with_a_server_behind_it(self):
        states = snapshot(cache_configured=True).component_states()

        assert states["cache"] == "ok"

    def test_a_server_that_did_not_answer(self):
        states = snapshot(
            cache_configured=True, cache=False, timed_out=("cache",)
        ).component_states()

        assert states["cache"] == "timeout"

    def test_neither_of_the_two_local_states_is_a_fault(self):
        """
        The half that keeps the distinction from costing anything.

        A cache nobody configured is not a broken cache, and neither is
        one keeping entries in this process: the documented local setup
        runs that way, and reporting it as a failure made a healthy
        install look broken.
        """
        for stores in (True, False):
            assert snapshot(cache_stores=stores).healthy is True

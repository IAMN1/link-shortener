"""
``InMemoryLinkCache`` and ``NullCache`` answer ``is_configured()`` the same and
do the opposite thing.

Both return ``False``, and the sentence at each said the same thing about
why. It is right for ``NullCache``, which stores nothing; for
``InMemoryLinkCache`` it is half the story, and every report built on that one
answer -- ``/health``, ``flask cache stats``, ``maintenance check-redis``,
``maintenance health`` -- collapses two situations into one line.

They are not one situation. A cache in the process holds entries that
another process cannot invalidate: measured on a live stack, a link
deleted with ``flask link delete`` went on being redirected to by the
running server for six minutes, surviving two ``cache clear`` runs, while
every one of those reports said there was no cache. With ``NullCache``
the same delete is seen at once, because nothing was held.

So the two are held apart here by what they do rather than by what they
say. If somebody makes ``InMemoryLinkCache`` answer ``True``, the guide's
"``\"cache\": \"disabled\"`` locally" goes with it and this file is where
they should be standing; if somebody makes ``NullCache`` store something,
the same.
"""

import hashlib

import pytest

from link_shortener.domain.entities.link import Link
from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.url_hash import UrlHash
from link_shortener.infrastructure.cache.memory_cache import InMemoryLinkCache
from link_shortener.infrastructure.cache.null_cache import NullCache


CODE = ShortCode("kept0rNot")
URL = "https://example.com/held-or-not"


@pytest.fixture
def in_the_process():
    return InMemoryLinkCache(prefix="test", link_ttl=60, stats_ttl=60)


@pytest.fixture
def nothing_at_all():
    return NullCache()


def a_link() -> Link:
    """One link, made the way the service makes one."""
    return Link.create(
        url_hash=UrlHash(hashlib.sha256(URL.encode()).hexdigest()),
        short_code=CODE,
        original_url=OriginalUrl(URL),
    )


class TestTheyAnswerTheSame:

    def test_neither_reports_a_backend(self, in_the_process, nothing_at_all):
        """
        The answer this file exists because of.

        Held for both in one place: two assertions in two files would let
        one of them change without the other being read.
        """
        assert in_the_process.is_configured() is False
        assert nothing_at_all.is_configured() is False

    def test_neither_can_be_unreachable(self, in_the_process, nothing_at_all):
        assert in_the_process.ping() is True
        assert nothing_at_all.ping() is True


class TestTheyDoNotBehaveTheSame:

    def test_the_one_in_the_process_holds_what_it_was_given(self, in_the_process):
        in_the_process.save(a_link())

        held = in_the_process.get_by_code(CODE)

        assert held is not None
        assert held.original_url.value == URL

    def test_the_null_one_holds_nothing(self, nothing_at_all):
        """
        Which is why one report for both is one report too few.

        The same call, the same answer from ``is_configured``, and the
        thing an operator is actually asking about goes the other way.
        """
        nothing_at_all.save(a_link())

        assert nothing_at_all.get_by_code(CODE) is None

    def test_clearing_reaches_only_what_was_held(
        self, in_the_process, nothing_at_all
    ):
        """``cache clear`` empties one of them and is a no-op on the other."""
        in_the_process.save(a_link())
        nothing_at_all.save(a_link())

        in_the_process.clear_all()
        nothing_at_all.clear_all()

        assert in_the_process.get_by_code(CODE) is None
        assert nothing_at_all.get_by_code(CODE) is None

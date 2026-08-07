"""
Tests for what batch creation does after its transaction closes.

Two things it did, and one it did not:

- it wrote every link of the batch into the cache **after** the unit of work
  had closed. A DELETE committed in between has already done its
  invalidating, so the entry came straight back and the redirect went on
  serving a link every API surface reported as gone -- for as long as
  ``CACHE_LINK_TTL``, an hour in production. Reproduced against real
  PostgreSQL and Redis in three rounds out of twelve. Nothing in the service
  could clear it afterwards: a second DELETE answered 404 without touching
  the cache, and the sweep never sees a row that is not there;
- it audited each creation inside the transaction, which is retried whole
  when it loses a race for a short code -- so the trail recorded creations
  that were then rolled back;
- it never dropped the statistics cache. Creation, deletion and the expiry
  sweep all do, each with a comment saying why; this path was missed, and
  ``/api/v1/stats`` then under-reported by up to a whole batch.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from link_shortener.application.use_cases.batch.batch_create_links import (
    BatchCreateLinksUseCase,
)
from link_shortener.application.context import RequestContext
from link_shortener.domain import Link, OriginalUrl, ShortCode, UrlHash


URL = "https://example.com/batched"


def _link(code="btch01"):
    """A link as the creator would have saved it."""
    return Link(
        id="link-1",
        url_hash=UrlHash("b" * 64),
        short_code=ShortCode(code),
        original_url=OriginalUrl(URL),
        created_at=datetime.now(timezone.utc),
    )


def _group():
    """One grouper output entry."""
    return {
        "hash": UrlHash("b" * 64),
        "original_url": OriginalUrl(URL),
        "urls": [URL],
        "is_valid": True,
    }


@pytest.fixture
def parts():
    """Every collaborator of the use case, stubbed."""
    saved = [_link()]

    grouper = Mock()
    grouper.group.return_value = {"b" * 64: _group()}

    fetcher = Mock()
    fetcher.fetch.return_value = ([], [_group()], [])

    creator = Mock()
    creator.max_attempts = 3
    creator.create_new_links.return_value = saved

    builder = Mock()
    builder.build_from_new_links.return_value = []

    uow = Mock()
    uow.links.save_many.return_value = saved
    uow.links.count_guest_links_by_identifier.return_value = 0

    return grouper, fetcher, creator, builder, uow, saved


@pytest.fixture
def use_case(parts):
    grouper, fetcher, creator, builder, uow, _ = parts

    @contextmanager
    def factory(*args, **kwargs):
        yield uow

    logger = Mock()
    logger.bind.return_value = Mock()
    audit = Mock()
    audit.bind.return_value = Mock()

    return BatchCreateLinksUseCase(
        uow_factory=factory,
        cache=Mock(),
        stats_cache=Mock(),
        base_url="https://short.link",
        logger=logger,
        audit_logger=audit,
        batch_limit=100,
        guest_link_limit=10,
        guest_link_window_days=1,
        default_guest_ttl_seconds=604800,
        grouper=grouper,
        fetcher=fetcher,
        creator=creator,
        builder=builder,
    )


def _context():
    return RequestContext(request_id="req-1", remote_addr="198.51.100.20")


class TestNothingIsWrittenToTheCacheAfterTheTransaction:
    """
    The write landed after the unit of work closed, so a DELETE that
    committed in between was undone by it.
    """

    def test_the_batch_does_not_warm_the_link_cache(self, use_case):
        use_case.execute([URL], _context())

        use_case.cache.save_many.assert_not_called()

    def test_it_does_not_reach_for_a_single_save_either(self, use_case):
        use_case.execute([URL], _context())

        use_case.cache.save.assert_not_called()


class TestTheTotalsAreDroppedWhenLinksAreCreated:
    """Otherwise ``/api/v1/stats`` under-reports by up to a whole batch."""

    def test_creating_links_drops_the_statistics_cache(self, use_case):
        use_case.execute([URL], _context())

        use_case.stats_cache.delete_stats.assert_called_once()

    def test_a_batch_that_creates_nothing_leaves_the_totals_alone(
        self, use_case, parts
    ):
        """The totals have not changed, so dropping them buys nothing."""
        _, fetcher, creator, _, uow, _ = parts
        fetcher.fetch.return_value = ([], [], [])
        creator.create_new_links.return_value = []
        uow.links.save_many.return_value = []

        use_case.execute([URL], _context())

        use_case.stats_cache.delete_stats.assert_not_called()


class TestTheAuditTrailRecordsWhatHappened:
    """
    The transaction is retried whole on a lost race, so a line written
    inside it can describe a creation that was rolled back.
    """

    def test_the_creation_is_audited_after_the_commit(self, use_case, parts):
        _, _, _, _, uow, _ = parts
        order = []
        uow.commit.side_effect = lambda: order.append("commit")
        audit = use_case.audit_logger.bind.return_value
        audit.log_url_created.side_effect = lambda **kw: order.append("audit")

        use_case.execute([URL], _context())

        assert order == ["commit", "audit"]


class TestRefreshingStatisticsActuallyRefreshes:
    """
    ``flask stats refresh`` printed "STATISTIC REFRESHED IN CACHE" over the
    same numbers it had just been handed: it called the use case, which
    answers from the cache on a hit, and touched nothing. It was
    ``stats show`` under another name -- and it is the command an operator
    reaches for when the totals look stale.
    """

    def test_the_cached_entry_is_dropped_before_reading(self):
        from link_shortener.infrastructure.cli.commands.stats import refresh_stats

        order = []
        stats_cache = Mock()
        stats_cache.delete_stats.side_effect = lambda: order.append("drop")

        use_case = Mock()
        use_case.execute.side_effect = lambda context: order.append("read") or Mock(
            total_urls=1, total_clicks=0, avg_clicks_per_url=0.0, popular_links=[]
        )

        refresh_stats(use_case, stats_cache)

        assert order == ["drop", "read"]

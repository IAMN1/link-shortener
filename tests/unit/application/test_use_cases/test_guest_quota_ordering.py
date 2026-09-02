"""
Tests that the guest allowance is read behind the lock, not before it.

The lock is what makes counting and inserting one decision. Taken after the
count it protects nothing: the number it guards has already been read, and
every simultaneous request from the same guest read the same one.

Both creation paths, because both spend the same allowance. They now read
it through one function, and the point of testing each separately is that
neither can quietly stop: a path that grows its own lock-and-count again
looks identical from outside, right up until the order in it is wrong.

The concurrency test beside this one proves the lock works. It reproduces
the protocol itself rather than calling either use case, so it goes on
passing when the production path stops taking the lock at all -- these are
the tests that notice that.
"""

from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.application.use_cases.batch.batch_create_links import (
    BatchCreateLinksUseCase,
)
from link_shortener.application.use_cases.batch.groups import UrlGroup
from link_shortener.application.use_cases.links.create_short_link import (
    CreateShortLinkUseCase,
)
from link_shortener.domain import OriginalUrl, ShortCode, UrlHash


URL = "https://example.com/quota"
HASH = UrlHash("b" * 64)
GUEST = "203.0.113.70"


@pytest.fixture
def calls():
    """Records the order of the repository calls that matter."""
    return []


@pytest.fixture
def use_case(calls):
    """Use case over a repository that records its call order."""
    repo = Mock()
    repo.find_by_code.return_value = None
    repo.find_live_by_hash.return_value = None
    repo.save.side_effect = lambda link: link

    def lock(identifier):
        calls.append(("lock", identifier))

    def count(identifier, days):
        calls.append(("count", identifier))
        return 0

    repo.lock_guest_quota.side_effect = lock
    repo.count_guest_links_by_identifier.side_effect = count

    unit = Mock()
    unit.links = repo

    @contextmanager
    def factory(*args, **kwargs):
        yield unit

    cache = Mock()
    cache.get_by_hash.return_value = None

    hash_calculator = Mock()
    hash_calculator.calculate.return_value = HASH

    code_generator = Mock()
    code_generator.generate_unique.return_value = ShortCode("quota1")

    logger = Mock()
    logger.bind.return_value = Mock()
    audit_logger = Mock()
    audit_logger.bind.return_value = Mock()

    return CreateShortLinkUseCase(
        uow_factory=factory,
        cache=cache,
        stats_cache=cache,
        hash_calculator=hash_calculator,
        code_generator=code_generator,
        base_url="https://short.link",
        logger=logger,
        audit_logger=audit_logger,
        allowed_schemes=["http", "https"],
        max_url_length=2048,
        allow_internal_targets=False,
        guest_link_limit=10,
        guest_link_window_days=1,
        default_guest_ttl_seconds=604800,
        max_ttl_seconds=10 * 365 * 24 * 3600,
        max_collision_attempts=3,
    )


def _context(guest=GUEST, user=None):
    """Build a request context."""
    return RequestContext(
        request_id="req-1",
        remote_addr=guest,
        request_path="/api/v1/shorten",
        request_method="POST",
        current_user=user,
    )


class TestTheAllowanceIsReadBehindTheLock:
    """Order is the whole property here."""

    def test_the_lock_comes_first(self, use_case, calls):
        use_case.execute(URL, _context())

        assert calls[0][0] == "lock", calls
        assert calls[1][0] == "count", calls

    def test_it_locks_the_caller_s_own_identifier(self, use_case, calls):
        use_case.execute(URL, _context())

        assert calls[0][1] == GUEST

    def test_nothing_is_locked_for_a_caller_with_no_allowance_to_spend(
        self, use_case, calls
    ):
        """A context with no address is the CLI, which has no quota at all."""
        use_case.execute(URL, _context(guest=None))

        assert calls == []


@pytest.fixture
def batch_use_case(calls):
    """The batch path over the same recording repository."""
    repo = Mock()
    repo.save_many.side_effect = lambda links: links

    def lock(identifier):
        calls.append(("lock", identifier))

    def count(identifier, days):
        calls.append(("count", identifier))
        return 0

    repo.lock_guest_quota.side_effect = lock
    repo.count_guest_links_by_identifier.side_effect = count

    unit = Mock()
    unit.links = repo

    @contextmanager
    def factory(*args, **kwargs):
        yield unit

    group = UrlGroup(hash=HASH, original_url=OriginalUrl(URL), urls=[URL])

    grouper = Mock()
    grouper.group.return_value = ([group], [])

    fetcher = Mock()
    fetcher.fetch.return_value = ([], [group], [])

    creator = Mock()
    creator.create_new_links.return_value = []

    builder = Mock()
    builder.build_from_new_links.return_value = []

    logger = Mock()
    logger.bind.return_value = Mock()
    audit_logger = Mock()
    audit_logger.bind.return_value = Mock()

    return BatchCreateLinksUseCase(
        uow_factory=factory,
        stats_cache=Mock(),
        base_url="https://short.link",
        logger=logger,
        audit_logger=audit_logger,
        batch_limit=100,
        guest_link_limit=10,
        guest_link_window_days=1,
        default_guest_ttl_seconds=604800,
        max_collision_attempts=3,
        grouper=grouper,
        fetcher=fetcher,
        creator=creator,
        builder=builder,
    )


class TestTheBatchReadsItBehindTheLockToo:
    """A batch is worth a whole quota to every concurrent caller without it."""

    def test_the_lock_comes_first(self, batch_use_case, calls):
        batch_use_case.execute([URL], _context())

        assert calls[0][0] == "lock", calls
        assert calls[1][0] == "count", calls

    def test_it_locks_the_caller_s_own_identifier(self, batch_use_case, calls):
        batch_use_case.execute([URL], _context())

        assert calls[0][1] == GUEST

    def test_nothing_is_locked_for_a_caller_with_no_allowance_to_spend(
        self, batch_use_case, calls
    ):
        """A context with no address is the CLI, which has no quota at all."""
        batch_use_case.execute([URL], _context(guest=None))

        assert calls == []

    def test_the_allowance_is_read_after_deduplication(
        self, batch_use_case, calls
    ):
        """Being handed a link that already exists creates nothing.

        So it costs nothing, and the single-link path says the same in a
        comment of its own. A batch that charged first refused a guest for
        URLs they had already shortened themselves.
        """
        batch_use_case.fetcher.fetch.return_value = ([], [], [])

        batch_use_case.execute([URL], _context())

        batch_use_case.fetcher.fetch.assert_called_once()
        assert calls[0][0] == "lock"

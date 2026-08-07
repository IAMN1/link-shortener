"""
Tests that the guest allowance is read behind the lock, not before it.

The lock is what makes counting and inserting one decision. Taken after the
count it protects nothing: the number it guards has already been read, and
every simultaneous request from the same guest read the same one.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from link_shortener.application.context import RequestContext
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

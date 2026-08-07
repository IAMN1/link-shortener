"""
Tests that losing a race with a concurrent creation is not a failure.

Whether a short code is free is decided by the unique index on
``urls.short_code``, not by the lookup that precedes the insert: between
the two, another request can commit. The check-then-insert shape is the
textbook race, and the loser used to surface as a 500 -- for something as
ordinary as a double-click.

The fix is the standard one: let the constraint decide, report the
violation, and retry the whole unit of work. By then the winner's row is
visible, so the retry either returns it as the existing link or generates a
code around it.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.application.use_cases.links.create_short_link import (
    CreateShortLinkUseCase,
)
from link_shortener.domain import (
    CodeGenerationError, Link, LinkConflictError, OriginalUrl, OwnerID,
    ShortCode, UrlHash
)


URL = "https://example.com/raced"
HASH = UrlHash("a" * 64)
CODE = "race01"


def _link(code=CODE, owner=None, clicks=0):
    """Build a stored link."""
    return Link(
        id="link-1",
        url_hash=HASH,
        short_code=ShortCode(code),
        original_url=OriginalUrl(URL),
        created_at=datetime.now(timezone.utc),
        clicks=clicks,
        owner=OwnerID(owner) if owner else None,
        guest_identifier=None if owner else "203.0.113.30",
    )


@pytest.fixture
def repo():
    """A repository that finds nothing and stores without complaint."""
    repository = Mock()
    repository.find_by_code.return_value = None
    repository.find_live_by_hash.return_value = None
    repository.count_guest_links_by_identifier.return_value = 0
    repository.save.side_effect = lambda link: link
    return repository


@pytest.fixture
def use_case(repo):
    """Use case over a null cache and a mock unit of work."""
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
    code_generator.generate_unique.return_value = ShortCode(CODE)
    code_generator.generate_fresh.return_value = ShortCode("fresh1")

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


def _context():
    """A guest request context."""
    return RequestContext(
        request_id="req-1",
        remote_addr="203.0.113.30",
        request_path="/api/v1/shorten",
        request_method="POST",
    )


class TestLosingTheRaceIsNotAFailure:
    """The loser of a race answers, it does not raise."""

    def test_the_winners_link_is_returned_as_existing(self, use_case, repo):
        winner = _link()

        def save(link):
            # First attempt loses; the winner's row is visible afterwards.
            repo.save.side_effect = lambda link: link
            repo.find_live_by_hash.return_value = winner
            raise LinkConflictError()

        repo.save.side_effect = save

        result = use_case.execute(URL, _context())

        assert result.is_new is False
        assert result.short_code == CODE

    def test_an_unrelated_collision_is_retried_with_another_code(
        self, use_case, repo
    ):
        """
        The winner took our code but shortened a different URL.

        Deduplication then still finds nothing, so the retry has to produce
        a link of its own rather than hand back somebody else's.
        """
        attempts = {"count": 0}

        def save(link):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise LinkConflictError()
            return link

        repo.save.side_effect = save

        result = use_case.execute(URL, _context())

        assert result.is_new is True
        assert attempts["count"] == 2

    def test_the_retry_is_bounded(self, use_case, repo):
        repo.save.side_effect = LinkConflictError()

        with pytest.raises(CodeGenerationError):
            use_case.execute(URL, _context())

        assert repo.save.call_count == use_case.max_collision_attempts

    def test_a_conflict_never_reaches_the_caller_as_itself(self, use_case, repo):
        """
        Whatever else happens, the caller must not see the storage-level
        conflict: it means nothing to them and used to arrive as a 500.
        """
        repo.save.side_effect = LinkConflictError()

        with pytest.raises(Exception) as caught:
            use_case.execute(URL, _context())

        assert not isinstance(caught.value, LinkConflictError)

"""
Tests that the account's links are deleted by the use case, not by the
foreign key.

The distinction is the whole point. ``urls.owner_id`` is ``ON DELETE
CASCADE``, so the rows would go either way -- and an integration test
against the database passes with the use case doing nothing at all, which
is how this was nearly missed. What the cascade cannot do is clear the
caches: a row that disappears behind the application leaves its entry in
the redirect cache and the link cache, and every level goes on answering
for a link that no longer exists until its TTL runs out, with nothing in the
service able to remove it.

So the deletion belongs to the use case, in the same transaction as the
account, and the constraint is the backstop for a deletion done outside the
application.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.application.use_cases.admin.users.delete_user import (
    DeleteUserUseCase,
)
from link_shortener.domain import (
    Link, OriginalUrl, OwnerID, ShortCode, UrlHash
)


USER_ID = "owner-being-deleted"


def _link(code):
    """A link owned by the account under deletion."""
    digest = "".join(f"{ord(char):02x}" for char in code).ljust(64, "0")[:64]
    return Link(
        id=f"link-{code}",
        url_hash=UrlHash(digest),
        short_code=ShortCode(code),
        original_url=OriginalUrl(f"https://example.com/{code}"),
        created_at=datetime.now(timezone.utc),
        owner=OwnerID(USER_ID),
    )


@pytest.fixture
def owned():
    return [_link("owned1"), _link("owned2")]


@pytest.fixture
def uow(owned):
    unit = Mock()
    unit.links.delete_by_owner.return_value = owned
    # Not the last administrator, and not an administrator at all.
    unit.users.find_by_id.return_value = None
    return unit


@pytest.fixture
def use_case(uow):
    @contextmanager
    def factory(*args, **kwargs):
        yield uow

    logger = Mock()
    logger.bind.return_value = Mock()
    audit = Mock()
    audit.bind.return_value = Mock()

    service = Mock()
    service.delete_user.return_value = True

    return DeleteUserUseCase(
        uow_factory=factory,
        user_service=service,
        cache=Mock(),
        redirect_cache=Mock(),
        stats_cache=Mock(),
        logger=logger,
        audit_logger=audit,
    )


def _context():
    return RequestContext(request_id="admin-delete")


class TestTheUseCaseDeletesTheLinksItself:

    def test_the_links_are_deleted_in_the_same_unit_of_work(
        self, use_case, uow
    ):
        use_case.execute(USER_ID, _context())

        uow.links.delete_by_owner.assert_called_once_with(USER_ID)

    def test_the_account_goes_too(self, use_case):
        result = use_case.execute(USER_ID, _context())

        assert result is True
        use_case.user_service.delete_user.assert_called_once()

    def test_an_account_that_is_not_there_stops_short_of_committing(
        self, use_case, uow
    ):
        use_case.user_service.delete_user.return_value = False

        assert use_case.execute(USER_ID, _context()) is False
        uow.commit.assert_not_called()


class TestEveryCacheLevelIsCleared:
    """What the foreign key cannot do, and the reason for doing this here."""

    def test_each_deleted_link_leaves_the_link_cache(
        self, use_case, owned
    ):
        use_case.execute(USER_ID, _context())

        assert use_case.cache.delete.call_count == len(owned)

    def test_each_deleted_link_leaves_the_redirect_cache(
        self, use_case, owned
    ):
        use_case.execute(USER_ID, _context())

        assert use_case.redirect_cache.delete_redirect.call_count == len(owned)

    def test_the_totals_are_dropped_once(self, use_case):
        use_case.execute(USER_ID, _context())

        use_case.stats_cache.delete_stats.assert_called_once()

    def test_an_account_with_no_links_touches_no_cache(self, use_case, uow):
        uow.links.delete_by_owner.return_value = []

        use_case.execute(USER_ID, _context())

        use_case.cache.delete.assert_not_called()
        use_case.stats_cache.delete_stats.assert_not_called()

    def test_a_failing_cache_does_not_fail_the_deletion(self, use_case):
        """The rows are already gone; the answer is still that they are."""
        use_case.cache.delete.side_effect = RuntimeError("redis is down")

        assert use_case.execute(USER_ID, _context()) is True


class TestTheDeletionIsAudited:

    def test_every_deleted_link_is_recorded(self, use_case, owned):
        use_case.execute(USER_ID, _context())

        audit = use_case.audit_logger.bind.return_value
        assert audit.log_url_deleted.call_count == len(owned)

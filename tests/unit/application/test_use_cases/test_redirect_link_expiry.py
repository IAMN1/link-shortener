"""Unit tests for expiry handling on the redirect path."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, Mock

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.cache.redirect_cache import CachedRedirect
from link_shortener.application.use_cases.links.redirect_link import RedirectLinkUseCase
from link_shortener.domain import (
    Link, LinkExpiredError, OriginalUrl, ShortCode, UrlHash
)


SHORT_CODE = "abc123"
ORIGINAL_URL = "https://example.com/target"


def _link(expires_in_seconds):
    """
    Build a link that expires relative to now.

    Args:
        expires_in_seconds: Negative for an already-expired link.

    Returns:
        A Link entity.
    """
    now = datetime.now(timezone.utc)
    return Link(
        id="link-1",
        url_hash=UrlHash("a" * 64),
        short_code=ShortCode(SHORT_CODE),
        original_url=OriginalUrl(ORIGINAL_URL),
        created_at=now,
        expires_at=now + timedelta(seconds=expires_in_seconds),
    )


def _entry(expires_in_seconds=3600, url=ORIGINAL_URL, code=SHORT_CODE):
    """
    Build an L1 entry.

    Args:
        expires_in_seconds: Negative for an already-expired entry.
        url: Destination recorded in the entry.
        code: Short code the entry claims to belong to.

    Returns:
        A ``CachedRedirect``.
    """
    return CachedRedirect(
        short_code=code,
        original_url=url,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds),
    )


@pytest.fixture
def use_case():
    """A redirect use case with every dependency mocked."""
    uow = Mock()
    factory = Mock(return_value=MagicMock())
    factory.return_value.__enter__ = Mock(return_value=uow)
    factory.return_value.__exit__ = Mock(return_value=False)

    logger = Mock()
    logger.bind.return_value = Mock()
    audit = Mock()
    audit.bind.return_value = Mock()

    case = RedirectLinkUseCase(
        uow_factory=factory,
        link_cache=Mock(),
        redirect_cache=Mock(),
        logger=logger,
        audit_logger=audit,
        task_queue=Mock(),
    )
    case.uow = uow
    return case


class TestL1AnswersOnItsOwn:
    """
    A hit in L1 completes the request. That is the level's entire purpose.

    While L1 held a bare URL string it could not say whether the link had
    expired, so every hit still had to consult L2, and an L2 miss still went
    to the repository. The level cost a round trip and saved nothing.
    """

    def test_an_l1_hit_does_not_consult_l2_or_the_repository(self, use_case):
        use_case.redirect_cache.get_redirect.return_value = _entry()

        result = use_case.execute(SHORT_CODE, RequestContext(request_id="t"))

        assert result == ORIGINAL_URL
        use_case.link_cache.get_by_code.assert_not_called()
        use_case.uow.links.find_by_code.assert_not_called()

    def test_a_permanent_link_is_served_from_l1(self, use_case):
        use_case.redirect_cache.get_redirect.return_value = CachedRedirect(
            short_code=SHORT_CODE, original_url=ORIGINAL_URL, expires_at=None
        )

        result = use_case.execute(SHORT_CODE, RequestContext(request_id="t"))

        assert result == ORIGINAL_URL
        use_case.link_cache.get_by_code.assert_not_called()


class TestExpiredIsNeverServed:
    """
    No combination of populated levels may produce an expired redirect.

    Each level is checked against the expiry it carries itself, so the
    answer does not depend on which levels happen to be warm.
    """

    def test_expired_entry_in_l1(self, use_case):
        # Its TTL is capped at the link's lifetime, so it should have
        # vanished by itself -- but the cache server's clock is not ours.
        use_case.redirect_cache.get_redirect.return_value = _entry(-60)

        with pytest.raises(LinkExpiredError):
            use_case.execute(SHORT_CODE, RequestContext(request_id="t"))

    def test_expired_link_in_l2_when_l1_missed(self, use_case):
        use_case.redirect_cache.get_redirect.return_value = None
        use_case.link_cache.get_by_code.return_value = _link(-60)

        with pytest.raises(LinkExpiredError):
            use_case.execute(SHORT_CODE, RequestContext(request_id="t"))

    def test_expired_link_in_the_repository_when_both_levels_missed(self, use_case):
        use_case.redirect_cache.get_redirect.return_value = None
        use_case.link_cache.get_by_code.return_value = None
        use_case.uow.links.find_by_code.return_value = _link(-60)

        with pytest.raises(LinkExpiredError):
            use_case.execute(SHORT_CODE, RequestContext(request_id="t"))

    def test_an_expired_l1_entry_is_refused_even_if_l2_is_alive(self, use_case):
        # The levels expire independently. A live entity elsewhere does not
        # make a dead entry servable.
        use_case.redirect_cache.get_redirect.return_value = _entry(-60)
        use_case.link_cache.get_by_code.return_value = _link(3600)

        with pytest.raises(LinkExpiredError):
            use_case.execute(SHORT_CODE, RequestContext(request_id="t"))


class TestL1IsWarmedFromTheLevelsBelow:
    """An L1 miss must not stay a miss forever."""

    def test_an_l2_hit_warms_l1_with_the_expiry(self, use_case):
        link = _link(3600)
        use_case.redirect_cache.get_redirect.return_value = None
        use_case.link_cache.get_by_code.return_value = link

        result = use_case.execute(SHORT_CODE, RequestContext(request_id="t"))

        assert result == ORIGINAL_URL
        # Without the expiry the entry could not answer on its own next
        # time, and the level would be useless again.
        use_case.redirect_cache.save_redirect.assert_called_once()
        args = use_case.redirect_cache.save_redirect.call_args[0]
        assert args[1] == ORIGINAL_URL
        assert args[2] == link.expires_at

    def test_a_repository_hit_populates_the_cache(self, use_case):
        use_case.redirect_cache.get_redirect.return_value = None
        use_case.link_cache.get_by_code.return_value = None
        use_case.uow.links.find_by_code.return_value = _link(3600)

        result = use_case.execute(SHORT_CODE, RequestContext(request_id="t"))

        assert result == ORIGINAL_URL
        # link_cache.save writes the redirect key too, under the same rules.
        use_case.link_cache.save.assert_called_once()


class TestUnvouchableEntriesFallThrough:
    """
    An entry the cache will not vouch for is reported as a miss, and a miss
    is always safe: it sends the request to the levels that can answer.

    Which entries those are is the cache's business -- unreadable values,
    entries written before the format carried an expiry, entries found
    under someone else's key. Here we only pin that the use case treats the
    resulting miss as a miss rather than as an absence of a link.
    """

    def test_a_miss_from_l1_still_resolves_through_the_repository(self, use_case):
        use_case.redirect_cache.get_redirect.return_value = None
        use_case.link_cache.get_by_code.return_value = None
        use_case.uow.links.find_by_code.return_value = _link(3600)

        result = use_case.execute(SHORT_CODE, RequestContext(request_id="t"))

        assert result == ORIGINAL_URL

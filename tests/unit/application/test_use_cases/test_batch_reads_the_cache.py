"""Tests for the half of batch lookup that nothing in the suite ran.

``BatchLinkFetcher`` asks the cache first and the repository second, and the
cache half was never reached: with the suite at 96% coverage, every line
that runs when the cache answers -- the items built from a cached hit, the
early return when the whole batch was cached, and the whole of ``_confirm``
-- sat outside every test.

``_confirm`` is the one that matters. A cached entry names a link that
existed when it was written, and under ``allkeys-lru`` it can easily outlive
the row: serving it unchecked hands back codes for links that have been
deleted or have expired. The method exists to check each hit against the
repository and drop the ones that fail, and the reasoning behind it is
written out at length above a body that has never once executed.

The builder's two other unrun branches are here too, for the same reason:
what marks a repeated URL as a duplicate is what the aggregate counts read
to avoid reporting it as a repository hit.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from link_shortener.application.use_cases.batch.fetcher import BatchLinkFetcher
from link_shortener.application.use_cases.batch.groups import UrlGroup
from link_shortener.application.use_cases.batch.response_builder import (
    BatchResponseBuilder,
)
from link_shortener.domain import (
    DedupScope, Link, OriginalUrl, OwnerID, ShortCode, UrlHash
)


BASE_URL = "https://short.link"
OWNER = "owner-a"
URL = "https://example.com/cached"
HASH = UrlHash("c" * 64)


def _scope():
    return DedupScope.for_owner(OWNER)


def _link(code="cch001", url=URL, url_hash=HASH, expires_at=None):
    """A link as storage holds it."""
    return Link(
        id="link-cached",
        url_hash=url_hash,
        short_code=ShortCode(code),
        original_url=OriginalUrl(url),
        created_at=datetime.now(timezone.utc),
        owner=OwnerID(OWNER),
        expires_at=expires_at,
    )


def _group(urls=None, url_hash=HASH, url=URL):
    return UrlGroup(
        hash=url_hash, original_url=OriginalUrl(url), urls=urls or [url]
    )


@pytest.fixture
def cache():
    return Mock()


@pytest.fixture
def repository():
    repo = Mock()
    repo.find_live_by_hashes.return_value = {}
    return repo


class TestABatchTheCacheAnswers:
    """The path taken when a hash is already known."""

    def test_a_confirmed_hit_is_reported_without_a_repository_lookup(
        self, cache, repository
    ):
        """The point of the cache: the batch stops before the second query."""
        link = _link()
        cache.get_by_hashes.return_value = {HASH: link}
        repository.find_by_codes.return_value = {link.short_code: link}

        results, to_create, found = BatchLinkFetcher(cache).fetch(
            repository=repository, groups=[_group()],
            base_url=BASE_URL, scope=_scope(),
        )

        assert [r.from_cache for r in results] == [True]
        assert (to_create, found) == ([], [])
        repository.find_live_by_hashes.assert_not_called()

    def test_every_url_of_a_cached_group_gets_its_own_item(
        self, cache, repository
    ):
        """One group is many input URLs, and the caller asked about each."""
        link = _link()
        cache.get_by_hashes.return_value = {HASH: link}
        repository.find_by_codes.return_value = {link.short_code: link}
        group = _group(urls=[URL, URL, URL])

        results, _, _ = BatchLinkFetcher(cache).fetch(
            repository=repository, groups=[group],
            base_url=BASE_URL, scope=_scope(),
        )

        assert len(results) == 3
        assert all(r.short_code == "cch001" for r in results)

    def test_an_empty_batch_asks_nothing_of_either(self, cache, repository):
        BatchLinkFetcher(cache).fetch(
            repository=repository, groups=[],
            base_url=BASE_URL, scope=_scope(),
        )

        cache.get_by_hashes.assert_not_called()
        repository.find_by_codes.assert_not_called()


class TestACachedHitIsCheckedAgainstStorage:
    """
    An entry can outlive the row it describes. Each of these is a way for
    that to happen, and each has to end with the entry dropped and the
    group sent on to be created rather than the stale code handed back.
    """

    def _fetch(self, cache, repository, stored):
        cache.get_by_hashes.return_value = {HASH: _link()}
        repository.find_by_codes.return_value = stored
        return BatchLinkFetcher(cache).fetch(
            repository=repository, groups=[_group()],
            base_url=BASE_URL, scope=_scope(),
        )

    def test_an_entry_for_a_deleted_link_is_dropped(self, cache, repository):
        results, to_create, _ = self._fetch(
            cache, repository, {ShortCode("cch001"): None}
        )

        assert results == []
        assert len(to_create) == 1
        cache.delete.assert_called_once()

    def test_an_entry_whose_row_now_holds_another_url_is_dropped(
        self, cache, repository
    ):
        """The code was reissued: same code, different address behind it."""
        other = _link(url="https://example.com/other", url_hash=UrlHash("d" * 64))

        results, to_create, _ = self._fetch(
            cache, repository, {ShortCode("cch001"): other}
        )

        assert results == []
        assert len(to_create) == 1
        cache.delete.assert_called_once()

    def test_an_entry_from_another_scope_is_dropped(self, cache, repository):
        """Deduplication is per owner: a hit outside the scope is not a hit."""
        someone_else = Link(
            id="link-theirs",
            url_hash=HASH,
            short_code=ShortCode("cch001"),
            original_url=OriginalUrl(URL),
            created_at=datetime.now(timezone.utc),
            owner=OwnerID("owner-b"),
        )

        results, to_create, _ = self._fetch(
            cache, repository, {ShortCode("cch001"): someone_else}
        )

        assert results == []
        assert len(to_create) == 1

    def test_an_expired_link_is_dropped(self, cache, repository):
        """Handing it back returns a code that answers 410."""
        expired = _link(
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1)
        )

        results, to_create, _ = self._fetch(
            cache, repository, {ShortCode("cch001"): expired}
        )

        assert results == []
        assert len(to_create) == 1
        cache.delete.assert_called_once()

    def test_nothing_is_asked_of_storage_when_the_cache_had_nothing(
        self, cache, repository
    ):
        """``_confirm`` returns early rather than querying for an empty set."""
        cache.get_by_hashes.return_value = {HASH: None}

        BatchLinkFetcher(cache).fetch(
            repository=repository, groups=[_group()],
            base_url=BASE_URL, scope=_scope(),
        )

        repository.find_by_codes.assert_not_called()


class TestRepeatedUrlsInOneGroup:
    """
    What the aggregate counts rely on. ``from_db_count`` excludes items
    carrying ``duplicate_of``, so if the builder stopped marking them the
    response would go back to reporting repository hits nobody made -- and
    the arithmetic test on the DTO would stay green throughout.
    """

    def test_the_first_url_is_the_new_link_and_the_rest_point_at_it(self):
        link = _link()
        group = _group(urls=[URL, URL, URL])

        items = BatchResponseBuilder.build_from_new_links(
            [group], [link], BASE_URL
        )

        assert [i.is_new for i in items] == [True, False, False]
        assert [i.duplicate_of for i in items] == [None, URL, URL]
        assert all(i.short_code == "cch001" for i in items)

    def test_only_the_new_one_carries_the_identifier_for_the_token(self):
        """The deletion token is the link's handle, and there is one link."""
        link = _link()
        group = _group(urls=[URL, URL])

        items = BatchResponseBuilder.build_from_new_links(
            [group], [link], BASE_URL
        )

        assert items[0].link_id == "link-cached"
        assert items[1].link_id is None


class TestAGroupThatWasNeverStored:
    """
    The safeguard. It should not happen -- the creator returns a link per
    group -- but reporting nothing at all for those URLs would answer a
    caller's address with silence.
    """

    def test_every_url_of_the_missing_group_is_refused_by_name(self):
        items = BatchResponseBuilder.build_from_new_links(
            [_group(urls=[URL, URL])], [], BASE_URL
        )

        assert [i.success for i in items] == [False, False]
        assert all(i.error.code == "LINK_NOT_STORED" for i in items)

    def test_the_refusal_is_marked_for_translation(self):
        """Like every other sentence the batch carries per item."""
        items = BatchResponseBuilder.build_from_new_links(
            [_group()], [], BASE_URL
        )

        assert items[0].error.template == "The link could not be stored"

    def test_the_groups_that_were_stored_are_still_reported(self):
        """One missing group must not cost the rest of the batch."""
        link = _link()
        other = _group(urls=["https://example.com/other"],
                       url_hash=UrlHash("e" * 64),
                       url="https://example.com/other")

        items = BatchResponseBuilder.build_from_new_links(
            [_group(), other], [link], BASE_URL
        )

        assert [i.success for i in items] == [True, False]

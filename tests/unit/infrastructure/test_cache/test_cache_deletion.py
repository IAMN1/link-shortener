"""
Tests for what a cache deletion has to remove.

The deduplication entry is keyed by hash and scope, so neither of them can be
recovered from a short code. Reading the code entry first to learn the hash
fails under ``allkeys-lru``, where the two keys are evicted independently:
whenever the code entry has gone first, the hash
entry survived the deletion and went on offering a link that no longer
exists.
"""

from unittest.mock import Mock

import pytest

from link_shortener.domain import (
    DedupScope, Link, OriginalUrl, OwnerID, ShortCode, UrlHash
)
from link_shortener.infrastructure.cache.memory_cache import InMemoryLinkCache
from link_shortener.infrastructure.cache.redis_cache import RedisLinkCache


HASH = UrlHash("c" * 64)
CODE = "del123"


@pytest.fixture
def link():
    """A guest link, so the scope is more than the default."""
    return Link.create(
        url_hash=HASH,
        short_code=ShortCode(CODE),
        original_url=OriginalUrl("https://example.com/gone"),
        guest_identifier="203.0.113.5",
    )


@pytest.fixture
def redis_cache():
    """A Redis cache over a stub client that records the commands it gets."""
    cache = RedisLinkCache.__new__(RedisLinkCache)
    cache.redis_url = "redis://stub"
    cache.logger = Mock()
    cache.ttl = 3600
    cache.stats_ttl = 60
    cache.retry_interval = 5
    cache._client = Mock()
    cache._available = True
    cache._last_attempt = 0.0

    from link_shortener.application import CacheKeyBuilder
    cache.key_gen = CacheKeyBuilder(prefix="test")
    return cache


class TestDeletionDoesNotDependOnTheCodeEntry:
    """The hash entry must go even when nothing else is left to read."""

    def test_redis_deletes_the_hash_key_without_reading_first(
        self, redis_cache, link
    ):
        redis_cache.delete(link)

        redis_cache._client.get.assert_not_called()
        deleted = set(redis_cache._client.delete.call_args[0])
        assert redis_cache.key_gen.for_url_hash(
            HASH.value, link.dedup_scope().token()
        ) in deleted

    def test_redis_deletes_all_three_keys(self, redis_cache, link):
        redis_cache.delete(link)

        deleted = set(redis_cache._client.delete.call_args[0])
        assert deleted == {
            redis_cache.key_gen.for_short_code(CODE),
            redis_cache.key_gen.for_redirect(CODE),
            redis_cache.key_gen.for_url_hash(
                HASH.value, link.dedup_scope().token()
            ),
        }

    def test_memory_cache_survives_a_missing_code_entry(self, link):
        cache = InMemoryLinkCache(prefix="test", link_ttl=3600, stats_ttl=60)
        cache.save(link)
        # Evict the code entry, as an LRU policy is free to do.
        cache._links.pop(cache.key_gen.for_short_code(CODE))

        cache.delete(link)

        assert cache.get_by_hash(HASH, link.dedup_scope()) is None


class TestRedirectDeletionIsSeparate:
    """
    ``delete_redirect`` touches the redirect entry and nothing else.

    One object implements both cache ports, so the two deletions have to be
    tellable apart by name.
    """

    def test_only_the_redirect_key_goes(self, redis_cache):
        redis_cache.delete_redirect(ShortCode(CODE))

        redis_cache._client.delete.assert_called_once_with(
            redis_cache.key_gen.for_redirect(CODE)
        )


class TestScopedEntriesDoNotCollide:
    """Two callers shortening the same URL keep separate entries."""

    def test_one_scopes_entry_does_not_answer_for_another(self):
        cache = InMemoryLinkCache(prefix="test", link_ttl=3600, stats_ttl=60)
        owned = Link.create(
            url_hash=HASH,
            short_code=ShortCode("owned1"),
            original_url=OriginalUrl("https://example.com/gone"),
            owner=OwnerID("user-a"),
        )
        cache.save(owned)

        assert cache.get_by_hash(HASH, DedupScope.for_owner("user-a")) == owned
        assert cache.get_by_hash(HASH, DedupScope.for_owner("user-b")) is None
        assert cache.get_by_hash(HASH, DedupScope.for_guest("10.0.0.1")) is None
        assert cache.get_by_hash(HASH, DedupScope()) is None

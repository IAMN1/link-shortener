"""Unit tests for RedisLinkCache behaviour when Redis is unavailable."""

from unittest.mock import Mock, patch

import pytest
import redis

from link_shortener.domain import DedupScope, ShortCode, UrlHash
from link_shortener.infrastructure.cache.redis_cache import RedisLinkCache


def _cache_with_client(client):
    """
    Build a cache wired to a given Redis client, believed to be up.

    Args:
        client: Mock Redis client.

    Returns:
        A RedisLinkCache using it.
    """
    with patch.object(RedisLinkCache, "_connect", lambda self: None):
        cache = RedisLinkCache(
            redis_url="redis://unused",
            prefix="test",
            logger=Mock(),
            link_ttl=60,
            stats_ttl=60,
            connect_timeout=1,
            socket_timeout=1,
            retry_interval=3600,
            secret_key="unit-test-secret",
        )
    cache._client = client
    cache._available = True
    return cache


@pytest.fixture()
def downed_cache():
    """
    A cache whose Redis connection has already failed.

    This is the state ``_execute_read``/``_execute_write`` leave behind after
    an error: the client is dropped and reconnection is held off until the
    retry interval passes.
    """
    with patch.object(RedisLinkCache, "_connect", lambda self: None):
        cache = RedisLinkCache(
            redis_url="redis://unused",
            prefix="test",
            logger=Mock(),
            link_ttl=60,
            stats_ttl=60,
            connect_timeout=1,
            socket_timeout=1,
            retry_interval=3600,
            secret_key="unit-test-secret",
        )
    cache._client = None
    cache._available = False
    cache._last_attempt = float("inf")
    return cache


class TestReadsWhileDown:
    """Every read degrades to a miss instead of raising."""

    def test_get_by_code(self, downed_cache):
        # Passing a bound method (self._client.get) evaluated the dead client
        # while building the call, so this raised AttributeError before any
        # of the error handling could run.
        assert downed_cache.get_by_code(ShortCode("abc123")) is None

    def test_get_by_hash(self, downed_cache):
        assert downed_cache.get_by_hash(UrlHash("a" * 64), DedupScope()) is None

    def test_get_by_hashes(self, downed_cache):
        hashes = [UrlHash("a" * 64), UrlHash("b" * 64)]
        result = downed_cache.get_by_hashes(hashes, DedupScope())
        # One entry per requested hash, matching NullCache and the in-memory
        # cache. An empty dict satisfied "all values are None" vacuously, so
        # the old assertion checked nothing at all.
        assert set(result) == set(hashes)
        assert all(value is None for value in result.values())

    def test_get_redirect(self, downed_cache):
        assert downed_cache.get_redirect(ShortCode("abc123")) is None

    def test_get_stats(self, downed_cache):
        assert downed_cache.get_stats() is None

    def test_get_cache_info(self, downed_cache):
        assert downed_cache.get_cache_info() == {"error": "Redis unavailable"}


class TestCorruptedEntries:
    """A value we could not have written is a miss, not a crash."""

    def test_undecodable_redirect_entry(self):
        cache = _cache_with_client(Mock(**{"get.return_value": b"\xff\xfe\xfd"}))
        # Letting UnicodeDecodeError out turned the redirect into a 500.
        assert cache.get_redirect(ShortCode("abc123")) is None

    def test_unparsable_stats_entry(self):
        cache = _cache_with_client(Mock(**{"get.return_value": b"not-json-at-all"}))
        # The caller then rebuilds from the database instead of publishing
        # fabricated zeroes.
        assert cache.get_stats() is None


class TestRejectedCommands:
    """A refused command is not a broken connection."""

    def test_wrongtype_does_not_disable_the_cache(self):
        client = Mock()
        client.get.side_effect = redis.ResponseError("WRONGTYPE")
        cache = _cache_with_client(client)

        assert cache.get_by_code(ShortCode("abc123")) is None
        # The server answered; dropping the client here disabled the whole
        # cache for a retry interval because of one poisoned key.
        assert cache._available is True
        assert cache._client is client

    def test_connection_error_does_disable_the_cache(self):
        client = Mock()
        client.get.side_effect = redis.ConnectionError("refused")
        cache = _cache_with_client(client)

        assert cache.get_by_code(ShortCode("abc123")) is None
        assert cache._available is False
        assert cache._client is None


class TestWritesWhileDown:
    """Every write is a silent no-op instead of raising."""

    def test_save_redirect(self, downed_cache):
        downed_cache.save_redirect(ShortCode("abc123"), "https://example.com")

    def test_save_stats(self, downed_cache):
        downed_cache.save_stats({"links": 1})

    def test_delete_stats(self, downed_cache):
        downed_cache.delete_stats()

    def test_delete(self, downed_cache, sample_link):
        downed_cache.delete(sample_link)

    def test_delete_redirect(self, downed_cache):
        downed_cache.delete_redirect(ShortCode("abc123"))

    def test_clear_all(self, downed_cache):
        downed_cache.clear_all()


class TestOnlyOneCallerReconnects:
    """
    A crowd arriving during an outage must not each dial Redis.

    Every attempt costs the full connect plus socket timeout, so without
    this a service under load degrades on every request instead of on one
    per retry interval.
    """

    def test_concurrent_callers_do_not_each_pay_the_timeout(self):
        import threading
        import time as _time
        from unittest.mock import patch

        from link_shortener.infrastructure.cache.redis_cache import RedisLinkCache

        def slow_failure(*_args, **_kwargs):
            _time.sleep(0.05)
            raise redis.ConnectionError("connection refused")

        with patch("redis.from_url", side_effect=slow_failure) as from_url:
            # Construction itself fails: the cache starts disconnected.
            cache = RedisLinkCache(
                redis_url="redis://localhost:6379/0",
                prefix="test",
                logger=Mock(),
                link_ttl=60,
                stats_ttl=60,
                connect_timeout=1,
                socket_timeout=1,
                retry_interval=30,
                secret_key="unit-test-secret",
            )
            from_url.reset_mock()

            threads = [
                threading.Thread(target=cache._ensure_connection)
                for _ in range(20)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            # One reconnect for the whole crowd, not twenty.
            assert from_url.call_count <= 1

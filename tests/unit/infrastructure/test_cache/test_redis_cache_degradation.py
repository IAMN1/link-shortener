"""Unit tests for RedisLinkCache behaviour when Redis is unavailable."""

import json
from datetime import datetime, timezone
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


def _sealed(cache, key, payload):
    """A value written the way the cache writes one, signature and all."""
    return cache._seal(key, json.dumps(payload).encode("utf-8"))


class TestARedirectEntryTheCacheWillNotVouchFor:
    """
    Everything the decoder refuses, and it refuses by answering a miss.

    Redis outlives a deployment: an entry written by an older build, or by
    anything else sharing the instance, is read by this code. Only two of
    these refusals were held -- undecodable bytes and unparsable JSON --
    and the rest are the ones that matter more, because they are entries
    that parse and are still not this link's.
    """

    def _cache_returning(self, payload):
        cache = _cache_with_client(Mock())
        key = cache.key_gen.for_redirect("abc123")
        cache._client.get.return_value = _sealed(cache, key, payload)
        return cache

    def test_an_entry_this_cache_wrote_is_read_back(self):
        """The control: without it every refusal below is satisfied by a
        decoder that refuses everything."""
        cache = self._cache_returning({
            "short_code": "abc123",
            "url": "https://example.com/x",
            "expires_at": None,
        })

        entry = cache.get_redirect(ShortCode("abc123"))

        assert entry is not None
        assert entry.original_url == "https://example.com/x"

    def test_a_json_document_that_is_not_an_object(self):
        cache = self._cache_returning([1, 2, 3])

        assert cache.get_redirect(ShortCode("abc123")) is None

    def test_bytes_that_carry_the_signature_and_still_are_not_json(self):
        """Sealed by this cache and unreadable anyway -- which is what an
        entry written in the pre-envelope format is: a bare URL, signed,
        with no expiry to judge it by. ``TestCorruptedEntries`` above hands
        over unsigned bytes, so the seal refuses them before the decoder
        is ever reached, and these lines ran nowhere."""
        cache = _cache_with_client(Mock())
        key = cache.key_gen.for_redirect("abc123")
        cache._client.get.return_value = cache._seal(
            key, b"https://example.com/the-old-format"
        )

        assert cache.get_redirect(ShortCode("abc123")) is None

    @pytest.mark.parametrize(
        "payload",
        [
            {"url": "https://example.com/x", "expires_at": None},
            {"short_code": "abc123", "expires_at": None},
            {"short_code": "abc123", "url": 42, "expires_at": None},
            {"short_code": 42, "url": "https://example.com/x",
             "expires_at": None},
        ],
        ids=["no code", "no url", "url is not a string",
             "code is not a string"],
    )
    def test_an_entry_missing_a_field_or_carrying_the_wrong_type(self, payload):
        cache = self._cache_returning(payload)

        assert cache.get_redirect(ShortCode("abc123")) is None

    def test_an_expiry_that_is_not_a_string(self):
        cache = self._cache_returning({
            "short_code": "abc123", "url": "https://example.com/x",
            "expires_at": 1756296000,
        })

        assert cache.get_redirect(ShortCode("abc123")) is None

    def test_an_expiry_that_is_not_a_moment(self):
        cache = self._cache_returning({
            "short_code": "abc123", "url": "https://example.com/x",
            "expires_at": "the day after tomorrow",
        })

        assert cache.get_redirect(ShortCode("abc123")) is None

    def test_an_expiry_with_no_zone_on_it_is_read_as_utc(self):
        """The entry is JSON, so an expiry written by anything that dropped
        the offset comes back naive. Read as local time it would be judged
        against the host's clock -- a different answer in every deployment
        -- so the decoder pins it to UTC."""
        cache = self._cache_returning({
            "short_code": "abc123", "url": "https://example.com/x",
            "expires_at": "2099-01-01T00:00:00",
        })

        entry = cache.get_redirect(ShortCode("abc123"))

        assert entry is not None
        assert entry.expires_at.tzinfo is timezone.utc

    def test_an_entry_written_for_another_code_is_refused_and_reported(self):
        """A value found under one key and written for another is a mix-up,
        not a redirect: served, it sends the visitor to somebody else's
        destination."""
        cache = _cache_with_client(Mock())
        key = cache.key_gen.for_redirect("abc123")
        cache._client.get.return_value = _sealed(cache, key, {
            "short_code": "zzz999", "url": "https://example.com/elsewhere",
            "expires_at": None,
        })

        assert cache.get_redirect(ShortCode("abc123")) is None
        assert cache.logger.error.called


class TestAStatsEntryTheCacheWillNotVouchFor:

    def test_a_json_document_that_is_not_an_object(self):
        """The caller reads missing fields as zeroes and publishes them, so
        a list arriving here becomes a service reporting no links at all."""
        cache = _cache_with_client(Mock())
        key = cache.key_gen.for_stats()
        cache._client.get.return_value = _sealed(cache, key, [1, 2, 3])

        assert cache.get_stats() is None
        assert cache.logger.error.called

    def test_an_entry_this_cache_wrote_is_read_back(self):
        cache = _cache_with_client(Mock())
        key = cache.key_gen.for_stats()
        cache._client.get.return_value = _sealed(cache, key, {"total_urls": 7})

        assert cache.get_stats() == {"total_urls": 7}

    def test_bytes_that_carry_the_signature_and_still_are_not_json(self):
        """Same gap as on the redirect side: the corrupted-entry test above
        hands over unsigned bytes, which the seal refuses first."""
        cache = _cache_with_client(Mock())
        key = cache.key_gen.for_stats()
        cache._client.get.return_value = cache._seal(key, b"\xff\xfe\xfd")

        assert cache.get_stats() is None
        assert cache.logger.error.called


class TestAWriteThatTheServerRefuses:
    """A rejected write is not a broken connection, and neither is silent.

    The read side of this rule is held by ``TestRejectedCommands`` above;
    the write side was reached by nothing, so a ``WRONGTYPE`` on a write
    could have disabled the whole cache for a retry interval.
    """

    def test_a_rejected_command_leaves_the_cache_up(self):
        client = Mock()
        client.setex.side_effect = redis.ResponseError("WRONGTYPE")
        cache = _cache_with_client(client)

        cache.save_redirect(ShortCode("abc123"), "https://example.com/x")

        assert cache._available is True
        assert cache._client is client
        assert cache.logger.error.called

    def test_a_broken_connection_takes_the_cache_down(self):
        client = Mock()
        client.setex.side_effect = redis.ConnectionError("refused")
        cache = _cache_with_client(client)

        cache.save_redirect(ShortCode("abc123"), "https://example.com/x")

        assert cache._available is False
        assert cache._client is None


class TestWritingSeveralLinksAtOnce:

    def test_nothing_to_write_dials_nothing(self):
        """An empty batch is the ordinary end of a paged sweep, and a
        pipeline opened for it is a round trip for no rows."""
        client = Mock()
        cache = _cache_with_client(client)

        cache.save_many([])

        assert not client.pipeline.called

    def test_a_batch_goes_out_as_one_pipeline(self, sample_link):
        client = Mock()
        cache = _cache_with_client(client)

        cache.save_many([sample_link, sample_link])

        assert client.pipeline.call_count == 1
        client.pipeline.return_value.execute.assert_called_once()


class TestDeletingByCodeAlone:
    """Used where the link is already gone and only its code is known."""

    def test_it_removes_both_keys_a_code_names(self):
        client = Mock()
        client.delete.return_value = 2
        cache = _cache_with_client(client)

        assert cache.delete_by_code(ShortCode("abc123")) is True

        removed = set(client.delete.call_args.args)
        assert removed == {
            cache.key_gen.for_short_code("abc123"),
            cache.key_gen.for_redirect("abc123"),
        }


class TestALinkComingBackFromTheCache:
    """
    The entity is rebuilt from JSON, and three of its fields are moments.

    Written by an older build, or by a deployment whose clock handling
    differed, they come back without an offset -- and a naive stamp
    reaching the domain is an expiry judged against the host's local
    time. Nothing exercised the rebuild at all: the tests above stop at
    the redirect entry, which is a different, smaller shape.
    """

    def _read_back(self, cache, payload):
        key = cache.key_gen.for_short_code("abc123")
        cache._client.get.return_value = _sealed(cache, key, payload)
        return cache.get_by_code(ShortCode("abc123"))

    def _payload(self, **overrides):
        payload = {
            "id": "link-1",
            "url_hash": "a" * 64,
            "short_code": "abc123",
            "original_url": "https://example.com/x",
            "clicks": 3,
            "created_at": "2026-08-01T10:00:00",
            "last_accessed": None,
            "owner_id": None,
            "expires_at": None,
            "guest_identifier": None,
        }
        payload.update(overrides)
        return payload

    def test_a_link_this_cache_wrote_is_read_back(self):
        cache = _cache_with_client(Mock())

        link = self._read_back(cache, self._payload())

        assert link is not None
        assert link.short_code.value == "abc123"
        assert link.clicks == 3

    @pytest.mark.parametrize(
        "field", ["created_at", "last_accessed", "expires_at"],
    )
    def test_a_moment_with_no_zone_on_it_comes_back_as_utc(self, field):
        cache = _cache_with_client(Mock())

        link = self._read_back(
            cache, self._payload(**{field: "2026-08-01T10:00:00"})
        )

        assert getattr(link, field).tzinfo is timezone.utc

    @pytest.mark.parametrize(
        "field", ["created_at", "last_accessed", "expires_at"],
    )
    def test_a_moment_that_carries_its_zone_keeps_it(self, field):
        cache = _cache_with_client(Mock())

        link = self._read_back(
            cache, self._payload(**{field: "2026-08-01T10:00:00+00:00"})
        )

        assert getattr(link, field) == datetime(
            2026, 8, 1, 10, 0, tzinfo=timezone.utc
        )

    def test_an_entry_it_cannot_rebuild_is_a_miss_rather_than_an_error(self):
        """A field the entity refuses -- here a code no ``ShortCode`` will
        take. Raising would turn one bad key into a 500 on a path that has
        a database behind it."""
        cache = _cache_with_client(Mock())

        assert self._read_back(cache, self._payload(short_code="!!")) is None
        assert cache.logger.error.called


class TestWhatTheMonitoringReadAnswers:
    """``get_cache_info`` is what ``/api/v1/admin/health`` reads."""

    def test_it_names_the_figures_an_operator_reads(self):
        client = Mock()
        client.info.return_value = {
            "used_memory_human": "1.5M",
            "connected_clients": 4,
            "uptime_in_seconds": 3600,
            "keyspace_hits": 90,
            "keyspace_misses": 10,
        }
        cache = _cache_with_client(client)

        assert cache.get_cache_info() == {
            "used_memory": "1.5M",
            "connected_clients": 4,
            "uptime": 3600,
            "keyspace_hits": 90,
            "keyspace_misses": 10,
        }

    def test_a_server_that_reports_nothing_is_not_read_as_zero_traffic(self):
        """An older Redis, or one with the command restricted, answers
        without these fields. Reported as absent figures rather than as a
        cache nobody is hitting."""
        cache = _cache_with_client(Mock(**{"info.return_value": {}}))

        assert cache.get_cache_info()["used_memory"] == "N/A"


class TestClearingEverythingUnderThePrefix:

    def test_it_deletes_only_the_keys_this_cache_owns(self):
        client = Mock()
        client.keys.return_value = [b"test:a", b"test:b"]
        cache = _cache_with_client(client)

        cache.clear_all()

        assert client.keys.call_args.args[0] == f"{cache.key_gen.prefix}:*"
        assert set(client.delete.call_args.args) == {b"test:a", b"test:b"}

    def test_nothing_to_clear_deletes_nothing(self):
        """``DEL`` with no arguments is an error, not a no-op."""
        client = Mock()
        client.keys.return_value = []
        cache = _cache_with_client(client)

        cache.clear_all()

        assert not client.delete.called

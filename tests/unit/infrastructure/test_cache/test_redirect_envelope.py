"""
Unit tests for the L1 redirect entry stored by ``RedisLinkCache``.

The entry has to be able to answer a redirect on its own: it carries the
expiry next to the URL, and its own lifetime never outlasts the link's. What
it cannot vouch for, it reports as a miss -- never as an error, and never as
an answer.
"""

import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

from link_shortener.domain import Link, OriginalUrl, ShortCode, UrlHash
from link_shortener.infrastructure.cache.redis_cache import RedisLinkCache
from link_shortener.infrastructure.cache.signing import unseal


CODE = "abc123"
URL = "https://example.com/target"
LINK_TTL = 3600
SECRET = "envelope-test-secret"


@contextmanager
def _cache(client):
    """
    Provide a ``RedisLinkCache`` over a stubbed Redis client.

    Args:
        client: Stub standing in for the Redis client.

    Yields:
        A connected ``RedisLinkCache``.
    """
    with patch("redis.from_url", return_value=client):
        yield RedisLinkCache(
            redis_url="redis://localhost:6379/0",
            prefix="test",
            logger=Mock(),
            link_ttl=LINK_TTL,
            stats_ttl=60,
            connect_timeout=1,
            socket_timeout=1,
            retry_interval=0,
            secret_key=SECRET,
        )


def _client():
    """A Redis stub that answers PING and returns nothing for reads."""
    client = Mock()
    client.ping.return_value = True
    client.get.return_value = None
    return client


def _stored(client):
    """
    Return the (ttl, value) the cache passed to SETEX.

    The value is unsealed first: everything the cache writes is signed for
    the key it goes under, so the payload is not the outermost bytes.

    Args:
        client: The Redis stub that received the call.

    Returns:
        Tuple of TTL in seconds and the decoded JSON payload.
    """
    key, ttl, value = client.setex.call_args[0]
    payload = unseal(SECRET, key, value)
    assert payload is not None, "the cache wrote something it cannot read back"
    return ttl, json.loads(payload.decode("utf-8"))


def _link(expires_in_seconds=None):
    """
    Build a link, optionally with an expiry.

    Args:
        expires_in_seconds: Seconds until expiry, or ``None`` for permanent.

    Returns:
        A ``Link`` entity.
    """
    now = datetime.now(timezone.utc)
    expires_at = (
        now + timedelta(seconds=expires_in_seconds)
        if expires_in_seconds is not None
        else None
    )
    return Link(
        id="link-1",
        url_hash=UrlHash("a" * 64),
        short_code=ShortCode(CODE),
        original_url=OriginalUrl(URL),
        created_at=now,
        expires_at=expires_at,
    )


class TestTheEntryCarriesItsOwnExpiry:
    """Without it, an L1 hit cannot complete a request."""

    def test_the_expiry_is_stored_next_to_the_url(self):
        client = _client()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        with _cache(client) as cache:
            cache.save_redirect(ShortCode(CODE), URL, expires_at)

        _ttl, payload = _stored(client)
        assert payload["url"] == URL
        assert payload["expires_at"] == expires_at.isoformat()

    def test_the_entry_is_bound_to_its_key(self):
        # So an entry that ends up under the wrong key is refused rather
        # than served as a redirect to somewhere else.
        client = _client()

        with _cache(client) as cache:
            cache.save_redirect(ShortCode(CODE), URL, None)

        _ttl, payload = _stored(client)
        assert payload["short_code"] == CODE

    def test_a_round_trip_returns_what_was_stored(self):
        client = _client()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        with _cache(client) as cache:
            cache.save_redirect(ShortCode(CODE), URL, expires_at)
            client.get.return_value = client.setex.call_args[0][2]

            entry = cache.get_redirect(ShortCode(CODE))

        assert entry.original_url == URL
        assert entry.expires_at == expires_at
        assert entry.is_expired() is False


class TestTheEntryNeverOutlivesTheLink:
    """
    The TTL is capped at the link's remaining lifetime, so an expired entry
    disappears by construction rather than by anyone remembering to check.
    """

    def test_a_short_lived_link_gets_a_short_lived_entry(self):
        client = _client()
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=30)

        with _cache(client) as cache:
            cache.save_redirect(ShortCode(CODE), URL, expires_at)

        ttl, _payload = _stored(client)
        assert 0 < ttl <= 30

    def test_a_permanent_link_gets_the_full_cache_ttl(self):
        client = _client()

        with _cache(client) as cache:
            cache.save_redirect(ShortCode(CODE), URL, None)

        ttl, _payload = _stored(client)
        assert ttl == LINK_TTL

    def test_a_long_lived_link_is_still_capped_by_the_cache_ttl(self):
        client = _client()
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)

        with _cache(client) as cache:
            cache.save_redirect(ShortCode(CODE), URL, expires_at)

        ttl, _payload = _stored(client)
        assert ttl == LINK_TTL

    def test_an_already_expired_link_is_not_stored_at_all(self):
        client = _client()
        expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

        with _cache(client) as cache:
            cache.save_redirect(ShortCode(CODE), URL, expires_at)

        # Writing it would only create something that has to be refused on
        # the way out. SETEX would also reject the non-positive TTL.
        client.setex.assert_not_called()

    def test_saving_a_link_caps_its_redirect_entry_too(self):
        # save() writes the redirect key itself; a bare URL on the full
        # cache TTL there is exactly how an expired link outlived its entity.
        client = _client()
        pipeline = Mock()
        client.pipeline.return_value = pipeline

        with _cache(client) as cache:
            cache.save(_link(expires_in_seconds=30))

        redirect_calls = [
            call for call in pipeline.setex.call_args_list
            if "redirect" in call[0][0]
        ]
        assert len(redirect_calls) == 1
        ttl = redirect_calls[0][0][1]
        assert 0 < ttl <= 30

    def test_saving_an_expired_link_writes_no_redirect_entry(self):
        client = _client()
        pipeline = Mock()
        client.pipeline.return_value = pipeline

        with _cache(client) as cache:
            cache.save(_link(expires_in_seconds=-60))

        redirect_calls = [
            call for call in pipeline.setex.call_args_list
            if "redirect" in call[0][0]
        ]
        assert redirect_calls == []


class TestWhatCannotBeVouchedForIsAMiss:
    """
    Every rejection is a miss, never an exception: a miss sends the request
    on to the levels that can answer, while an error on the redirect path is
    a 500.
    """

    @pytest.mark.parametrize(
        "stored, reason",
        [
            (URL.encode("utf-8"), "the old format: a bare URL with no expiry"),
            (b"\xff\xfe\x00garbage", "not text at all"),
            (b"{not json", "not valid JSON"),
            (b'"just a string"', "JSON, but not an object"),
            (b'{"url": "https://x.example"}', "no short_code"),
            (b'{"short_code": "abc123"}', "no url"),
            (b'{"short_code": "abc123", "url": 42}', "url is not a string"),
            (
                b'{"short_code": "abc123", "url": "https://x.example",'
                b' "expires_at": "not-a-date"}',
                "unparsable expiry",
            ),
        ],
    )
    def test_unusable_values_are_reported_as_misses(self, stored, reason):
        client = _client()
        client.get.return_value = stored

        with _cache(client) as cache:
            assert cache.get_redirect(ShortCode(CODE)) is None, reason

    def test_an_entry_written_for_another_code_is_refused(self):
        # Redirecting on the strength of someone else's entry would send the
        # visitor somewhere they never asked for.
        client = _client()
        client.get.return_value = json.dumps(
            {"short_code": "other1", "url": URL, "expires_at": None}
        ).encode("utf-8")

        with _cache(client) as cache:
            assert cache.get_redirect(ShortCode(CODE)) is None

    def test_the_old_format_does_not_raise(self):
        # Entries written before this change are still in live caches. They
        # have to age out quietly, not take the redirect path down.
        client = _client()
        client.get.return_value = URL.encode("utf-8")

        with _cache(client) as cache:
            assert cache.get_redirect(ShortCode(CODE)) is None

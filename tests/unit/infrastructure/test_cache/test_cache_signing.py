"""
Writing to Redis is not the same thing as being believed.

Every value the cache stores is signed for the key it goes under, and a
value that does not verify is a miss. Before this, a single
``SET link_shortener:code:<code> '<valid JSON>'`` turned the redirect into
an open one: the entity was rebuilt from the payload verbatim and the
destination came out of it.

The Redis client is a stub -- there is no Redis here -- but the cache is
real, and so is the signing. What is being tested is what the cache accepts
back, so the thing that decides that must not be the thing standing in.
"""

import json
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

from link_shortener.domain import (
    DedupScope, Link, OriginalUrl, ShortCode, UrlHash,
)
from link_shortener.infrastructure.cache.redis_cache import RedisLinkCache
from link_shortener.infrastructure.cache.signing import seal, unseal


SECRET = "signing-test-secret"
OTHER_SECRET = "somebody-elses-key"
CODE = "sign01"
URL = "https://example.com/legitimate"
EVIL = "https://evil.example/pwned"


@contextmanager
def _cache(client, secret=SECRET):
    """A real ``RedisLinkCache`` over a stubbed client."""
    with patch("redis.from_url", return_value=client):
        yield RedisLinkCache(
            redis_url="redis://localhost:6379/0",
            prefix="test",
            logger=Mock(),
            link_ttl=3600,
            stats_ttl=60,
            connect_timeout=1,
            socket_timeout=1,
            retry_interval=0,
            secret_key=secret,
        )


@contextmanager
def freeze_forward(seconds):
    """Run the block as if ``seconds`` had passed."""
    real = time.time
    try:
        time.time = lambda: real() + seconds
        yield
    finally:
        time.time = real


def _client():
    """A stub answering PING, returning nothing until told otherwise."""
    client = Mock()
    client.ping.return_value = True
    client.get.return_value = None
    client.mget.return_value = [None]
    return client


def _link(code=CODE, url=URL):
    """A link entity."""
    return Link.create(
        url_hash=UrlHash("a" * 64),
        short_code=ShortCode(code),
        original_url=OriginalUrl(url),
    )


def _payload_written_for(client, key):
    """Find what the cache stored under a key, still sealed."""
    for call in client.setex.call_args_list:
        if call[0][0] == key:
            return call[0][2]
    for call in client.pipeline.return_value.setex.call_args_list:
        if call[0][0] == key:
            return call[0][2]
    raise AssertionError(f"nothing was written to {key}")


def _forged(payload: dict) -> bytes:
    """
    Build a forgery shaped like a real envelope.

    Everything but the signature is right: the payload, the separator, a
    plausible timestamp. So the only thing left that can refuse it is the
    signature itself.

    This matters. Written as bare JSON, these tests stayed green with
    signature checking switched off entirely -- a handwritten payload has
    no signature to split off, and is refused on shape long before any
    comparison happens. They were exercising the format check while
    claiming to exercise the signature.
    """
    body = json.dumps(payload).encode("utf-8")
    stamp = seal(SECRET, "any", b"x").rsplit(b".", 2)[1]
    return body + b"." + stamp + b"." + b"0" * 27


class TestForgedEntriesAreRefused:
    """A value this service did not write is a miss."""

    def test_a_handwritten_link_entry_is_not_served(self):
        client = _client()
        with _cache(client) as cache:
            key = cache.key_gen.for_short_code(CODE)
            # Exactly the reproduction from the audit: valid JSON of the
            # right shape, written straight into Redis -- wrapped in a
            # well-formed envelope so the signature is what has to refuse it.
            client.get.return_value = _forged({
                "id": "forged",
                "url_hash": "b" * 64,
                "short_code": CODE,
                "original_url": EVIL,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "clicks": 0,
                "last_accessed": None,
                "owner_id": None,
                "expires_at": None,
                "guest_identifier": None,
            })

            assert cache.get_by_code(ShortCode(CODE)) is None

    def test_a_handwritten_redirect_entry_is_not_served(self):
        client = _client()
        with _cache(client) as cache:
            client.get.return_value = _forged({
                "short_code": CODE,
                "url": EVIL,
                "expires_at": None,
            })

            assert cache.get_redirect(ShortCode(CODE)) is None

    def test_a_handwritten_stats_entry_is_not_served(self):
        client = _client()
        with _cache(client) as cache:
            client.get.return_value = _forged({
                "total_urls": 133337,
                "total_clicks": 999999,
                "avg_clicks_per_url": 7.5,
                "popular_links": [],
            })

            assert cache.get_stats() is None

    def test_an_entry_signed_with_another_key_is_not_served(self):
        """Holding the format is not holding the key."""
        client = _client()
        with _cache(client) as cache:
            key = cache.key_gen.for_redirect(CODE)
            payload = json.dumps(
                {"short_code": CODE, "url": EVIL, "expires_at": None}
            ).encode("utf-8")
            client.get.return_value = seal(OTHER_SECRET, key, payload)

            assert cache.get_redirect(ShortCode(CODE)) is None


class TestEntriesCannotBeMoved:
    """The signature covers the key, so a value is not portable."""

    def test_a_redirect_entry_moved_to_another_code_is_refused(self):
        client = _client()
        with _cache(client) as cache:
            # Legitimately sealed -- but for a different code's key.
            other_key = cache.key_gen.for_redirect("other1")
            payload = json.dumps(
                {"short_code": CODE, "url": URL, "expires_at": None}
            ).encode("utf-8")
            client.get.return_value = seal(SECRET, other_key, payload)

            assert cache.get_redirect(ShortCode(CODE)) is None

    def test_a_link_entry_moved_from_the_hash_key_is_refused(self):
        """
        The two keys carry the same bytes and different signatures, so an
        entry cannot be lifted from one onto the other.
        """
        client = _client()
        with _cache(client) as cache:
            link = _link()
            cache.save(link)

            code_key = cache.key_gen.for_short_code(CODE)
            hash_key = cache.key_gen.for_url_hash(
                link.url_hash.value, link.dedup_scope().token()
            )
            sealed_for_hash = _payload_written_for(client, hash_key)

            assert _payload_written_for(client, code_key) != sealed_for_hash

            client.get.return_value = sealed_for_hash
            assert cache.get_by_code(ShortCode(CODE)) is None


class TestWhatTheServiceWroteStillWorks:
    """The signature must not have broken the cache it protects."""

    def test_a_link_round_trips(self):
        client = _client()
        with _cache(client) as cache:
            link = _link()
            cache.save(link)

            key = cache.key_gen.for_short_code(CODE)
            client.get.return_value = _payload_written_for(client, key)

            restored = cache.get_by_code(ShortCode(CODE))

            assert restored is not None
            assert restored.original_url.value == URL

    def test_a_redirect_round_trips(self):
        client = _client()
        with _cache(client) as cache:
            cache.save_redirect(ShortCode(CODE), URL, None)

            key = cache.key_gen.for_redirect(CODE)
            client.get.return_value = _payload_written_for(client, key)

            entry = cache.get_redirect(ShortCode(CODE))

            assert entry is not None
            assert entry.original_url == URL

    def test_stats_round_trip(self):
        client = _client()
        with _cache(client) as cache:
            cache.save_stats({"total_urls": 3, "total_clicks": 9})

            key = cache.key_gen.for_stats()
            client.get.return_value = _payload_written_for(client, key)

            assert cache.get_stats() == {"total_urls": 3, "total_clicks": 9}

    def test_a_batch_lookup_opens_each_value_against_its_own_key(self):
        """
        ``mget`` returns values in one list, and each has to be checked
        against the key it came from rather than against the first one.
        """
        client = _client()
        with _cache(client) as cache:
            first, second = _link(code="sign01"), _link(code="sign02")
            second.url_hash = UrlHash("c" * 64)
            cache.save(first)
            cache.save(second)

            scope = first.dedup_scope()
            keys = [
                cache.key_gen.for_url_hash(first.url_hash.value, scope.token()),
                cache.key_gen.for_url_hash(second.url_hash.value, scope.token()),
            ]
            client.mget.return_value = [
                _payload_written_for(client, keys[0]),
                _payload_written_for(client, keys[1]),
            ]

            found = cache.get_by_hashes([first.url_hash, second.url_hash], scope)

            assert found[first.url_hash] is not None
            assert found[second.url_hash] is not None


class TestEveryReadPathGoesThroughTheVerifier:
    """
    Bare, unwrapped JSON: exactly what a build without signing wrote, and
    exactly what an attacker types by hand.

    These are the tests that fail if a read path stops verifying at all,
    because bare JSON is the one forgery that gets *believed* when the
    check is skipped -- it parses. An envelope-shaped forgery cannot prove
    it: strip the verification and the envelope is no longer valid JSON, so
    the value is refused anyway and the test passes for the wrong reason.
    Both shapes are therefore needed, and they prove different things.
    """

    def test_a_bare_link_entry_is_refused(self):
        client = _client()
        with _cache(client) as cache:
            client.get.return_value = json.dumps({
                "id": "bare",
                "url_hash": "b" * 64,
                "short_code": CODE,
                "original_url": EVIL,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "clicks": 0,
                "last_accessed": None,
                "owner_id": None,
                "expires_at": None,
                "guest_identifier": None,
            }).encode("utf-8")

            assert cache.get_by_code(ShortCode(CODE)) is None

    def test_a_bare_redirect_entry_is_refused(self):
        client = _client()
        with _cache(client) as cache:
            client.get.return_value = json.dumps(
                {"short_code": CODE, "url": EVIL, "expires_at": None}
            ).encode("utf-8")

            assert cache.get_redirect(ShortCode(CODE)) is None

    def test_a_bare_stats_entry_is_refused(self):
        client = _client()
        with _cache(client) as cache:
            client.get.return_value = json.dumps({
                "total_urls": 133337,
                "total_clicks": 999999,
                "avg_clicks_per_url": 7.5,
                "popular_links": [],
            }).encode("utf-8")

            assert cache.get_stats() is None


class TestOldEntriesAreARewarmNotAFailure:
    """A value from before signing is a miss, not an error."""

    def test_an_unsigned_entry_is_a_miss(self):
        client = _client()
        with _cache(client) as cache:
            client.get.return_value = b"https://example.com/pre-envelope"

            assert cache.get_redirect(ShortCode(CODE)) is None

    def test_garbage_is_a_miss(self):
        client = _client()
        with _cache(client) as cache:
            client.get.return_value = b"\xff\xfe not even text"

            assert cache.get_by_code(ShortCode(CODE)) is None


class TestTheSigningPrimitive:
    """Properties of ``seal``/``unseal`` on their own."""

    def test_a_sealed_payload_comes_back_intact(self):
        blob = seal(SECRET, "k", b"payload")
        assert unseal(SECRET, "k", blob) == b"payload"

    def test_a_tampered_payload_is_refused(self):
        blob = seal(SECRET, "k", b"payload")

        assert unseal(SECRET, "k", blob.replace(b"payload", b"payl0ad", 1)) is None

    def test_a_tampered_signature_is_refused(self):
        """
        The *first* character of the signature, deliberately.

        Overwriting the last one is what this test used to do, and it was
        green by chance: the signature is 20 bytes in base64url, 27
        characters carrying 162 bits, so two bits of the final character
        decode to nothing. "A" through "D" all mean the same signature.
        The encoder only ever emits "A" of those four, so writing "B" over
        an "A" -- which is what the test did whenever it found one --
        changed the text and not the value: one run in sixteen, measured at
        184 of 3000. Every bit of the first character is significant.
        """
        head, _, signature = seal(SECRET, "k", b"payload").rpartition(b".")
        replacement = b"A" if signature[:1] != b"A" else b"B"

        assert unseal(SECRET, "k", head + b"." + replacement + signature[1:]) is None

    def test_another_key_is_refused(self):
        assert unseal(SECRET, "other", seal(SECRET, "k", b"payload")) is None

    def test_another_secret_is_refused(self):
        assert unseal(OTHER_SECRET, "k", seal(SECRET, "k", b"payload")) is None

    def test_the_key_boundary_cannot_be_shifted(self):
        """
        A naive scheme that merely concatenates the key and the payload
        lets the boundary move: ``("ab", b"cd")`` and ``("a", b"bcd")``
        sign the same bytes. The key is the signer's salt, so they do not.

        Asserted through the public API rather than by picking the
        signature out of the format -- the property is what matters, and it
        should survive a change of scheme.
        """
        assert unseal(SECRET, "a", seal(SECRET, "ab", b"cd")) is None
        assert unseal(SECRET, "ab", seal(SECRET, "a", b"bcd")) is None

    @pytest.mark.parametrize("blob", [b"", b"nope", b"only.two", b"a.b.c"])
    def test_malformed_blobs_are_refused(self, blob):
        assert unseal(SECRET, "k", blob) is None

    def test_a_value_older_than_its_ttl_is_refused(self):
        """
        Freshness, and the reason it is inside the signature: a value
        captured while it was legitimate and written back later would
        otherwise resurrect whatever it described, for as long as whoever
        wrote it back cared to keep it there.
        """
        blob = seal(SECRET, "k", b"payload")

        assert unseal(SECRET, "k", blob, max_age_seconds=3600) == b"payload"
        with freeze_forward(seconds=7200):
            assert unseal(SECRET, "k", blob, max_age_seconds=3600) is None

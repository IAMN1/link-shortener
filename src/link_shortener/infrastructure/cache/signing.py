"""
Signing what the cache stores, so that writing to Redis is not the same
thing as being believed.

Every value the cache hands back used to be taken at face value. A single
``SET link_shortener:code:<code> '<valid JSON>'`` turned the redirect into
an open one -- the entity was rebuilt from the payload verbatim and the
destination came out of it. The same held for the redirect envelope, the
deduplication entry, and the service statistics, where a well-formed object
was published as fact.

Two properties are needed, and both are old problems with settled answers,
so this is a thin wrapper over ``itsdangerous`` rather than an HMAC written
here. The library ships with Flask, so it costs no new dependency, and it
is the same machinery that signs Flask's own session cookies.

*The value must not be portable.* The Redis key goes in as the signer's
``salt``, which derives a distinct signing key per cache key. An entry
legitimately written for one code therefore fails to verify under another
-- and unlike concatenating the key into the message by hand, the boundary
between key and payload cannot be shifted.

*The value must not be eternal.* ``TimestampSigner`` stamps the issue time
inside the signed message and ``max_age`` refuses anything older. Redis
enforces whatever TTL it was handed, and whoever can write to Redis can
hand it a different one, or none at all: an entry captured while it was
legitimate and written back later resurrects what it described -- a deleted
link redirecting again, statistics frozen on an old count. With the stamp
signed, the lifetime is ours rather than the cache server's, and it cannot
be pushed forward by whoever holds the bytes.

A value that does not verify is a miss, never an error. That is the rule
the rest of this package already follows: a miss sends the request on to
the levels that can answer, while an exception on the redirect path is a
500. Entries written before signing existed do not verify either, so a
deployment simply re-warms its cache.
"""

from typing import Optional

from itsdangerous import BadSignature, TimestampSigner


def seal(secret_key: str, cache_key: str, payload: bytes) -> bytes:
    """
    Wrap a payload so that only this service could have written it here,
    and only recently.

    Args:
        secret_key: Application signing key.
        cache_key: The Redis key the value will be stored under.
        payload: Serialized value.

    Returns:
        Bytes to store: ``<payload>.<timestamp>.<signature>``.
    """
    return _signer(secret_key, cache_key).sign(payload)


def unseal(
    secret_key: str,
    cache_key: str,
    blob: Optional[bytes],
    max_age_seconds: Optional[int] = None,
) -> Optional[bytes]:
    """
    Recover a payload, refusing anything this service did not write here
    and anything it wrote too long ago.

    Args:
        secret_key: Application signing key.
        cache_key: The Redis key the value was read from.
        blob: Raw bytes from Redis, or ``None`` for a plain miss.
        max_age_seconds: Reject values stamped longer ago than this.
            ``None`` accepts any age.

    Returns:
        The original payload, or ``None`` if the value is absent, unsigned,
        signed with a different key, signed for a different cache key, or
        older than ``max_age_seconds``.
    """
    if not blob:
        return None

    try:
        # SignatureExpired is a subclass of BadSignature, so an entry that
        # has aged out is refused by the same branch as a forged one. Both
        # mean the same thing to the caller: this is not an answer.
        return _signer(secret_key, cache_key).unsign(
            blob, max_age=max_age_seconds
        )
    except BadSignature:
        return None


def _signer(secret_key: str, cache_key: str) -> TimestampSigner:
    """
    Build the signer for one cache key.

    Args:
        secret_key: Application signing key.
        cache_key: The Redis key the value belongs to; used as the salt, so
            each key gets its own derived signing key.

    Returns:
        A configured ``TimestampSigner``.
    """
    return TimestampSigner(secret_key, salt=cache_key.encode("utf-8"))

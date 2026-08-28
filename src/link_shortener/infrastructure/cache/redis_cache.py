"""
Redis-backed cache with automatic reconnection and graceful degradation.

Implements every role ``ServiceCache`` names. A Redis that cannot be
reached turns every read into a miss rather than failing the request, and
both the failure and the recovery are logged -- degrading quietly for the
caller is not the same as degrading without a word.
"""

from datetime import datetime, timezone
import json
import time
from threading import Lock
from typing import Any, Dict, List, Optional

from link_shortener.application import (
    CachedRedirect, ServiceCache, Logger, CacheKeyBuilder
)
from link_shortener.domain import DedupScope, Link, OriginalUrl, ShortCode, UrlHash
from link_shortener.domain.value_objects.owner_id import OwnerID
from link_shortener.infrastructure.cache.signing import seal, unseal

import redis


class RedisLinkCache(ServiceCache):
    """
    Redis implementation of every cache role ``ServiceCache`` names.

    Stores link data as JSON and uses pipelines for batch operations.
    Implements a reconnection strategy to tolerate transient Redis failures.
    """

    def __init__(
        self, redis_url: str, prefix: str, logger: Logger, link_ttl: int,
        stats_ttl: int, connect_timeout: int, socket_timeout: int,
        retry_interval: int, secret_key: str
    ):
        """
        Args:
            redis_url: Redis connection URL (e.g., ``redis://...``).
            prefix: Key prefix for namespacing.
            logger: Application logger.
            link_ttl: TTL for link entries (seconds).
            stats_ttl: TTL for stats entries (seconds).
            connect_timeout: Connection timeout (seconds).
            socket_timeout: Socket timeout (seconds).
            retry_interval: Seconds between reconnection attempts.
            secret_key: Key every stored value is signed with, so that
                whoever can write to Redis cannot decide what this service
                believes.
        """
        self.redis_url = redis_url
        self.key_gen = CacheKeyBuilder(prefix=prefix)
        self.logger = logger
        self.secret_key = secret_key
        self.ttl = link_ttl
        self.stats_ttl = stats_ttl
        self.connect_timeout = connect_timeout
        self.socket_timeout = socket_timeout
        self.retry_interval = retry_interval

        self.cache_type = "Redis"

        # Internal state for failover
        self._reconnect_lock = Lock()
        # Annotated rather than inferred from this assignment: the attribute
        # holds None until ``_connect`` builds a client, and again whenever
        # a failure drops it.
        self._client: Optional[redis.Redis] = None
        self._available = False
        self._last_attempt = 0.0

        self._connect()

    def _connect(self):
        """Establish initial connection to Redis."""
        try:
            self._client = redis.from_url(
                self.redis_url, 
                socket_connect_timeout=self.connect_timeout, 
                socket_timeout=self.socket_timeout
            )
            self._client.ping()
            self._available = True
            
            self.logger.info("Redis connected successfully.")
        except redis.RedisError as e:
            self.logger.error(
                "Redis connection failed, running without cache",
                error=str(e),
                exc_info=True
            )
            self._available = False
            self._client = None
    
    def _ensure_connection(self) -> bool:
        """
        Report whether a connection is available, reconnecting if it is not.

        A client believed to be up is used without probing it first. Pinging
        before every operation doubled the round-trips of the cache it was
        meant to protect, and bought nothing: the connection can drop between
        the probe and the call anyway, so the operation has to survive a
        failure regardless -- which is what the execute helpers do, dropping
        the client when one occurs.

        Reconnection is throttled: it is retried only after
        ``retry_interval`` seconds have passed since the last attempt.

        Returns:
            True if a working Redis connection is available, False otherwise
        """

        if self._client is not None and self._available:
            return True

        # Exactly one caller per interval gets to reconnect. Reading the
        # clock and then stamping it is a race: every thread that arrives
        # while Redis is down sees the window open and dials it, each paying
        # the full connect and socket timeout. Under load that degrades
        # every request rather than one per interval. The winner stamps the
        # clock *before* trying, so the losers see a closed window.
        with self._reconnect_lock:
            if self._client is not None and self._available:
                return True
            if time.time() - self._last_attempt <= self.retry_interval:
                return False
            self._last_attempt = time.time()

        # Reconnect outside the lock: holding it across a connect that can
        # take the full timeout would queue everyone behind it anyway,
        # which is the problem this exists to prevent.
        try:
            client = redis.from_url(
                self.redis_url,
                socket_connect_timeout=self.connect_timeout,
                socket_timeout=self.socket_timeout
            )
            client.ping()
        except redis.RedisError as e:
            self.logger.error(
                "Redis reconnection failed",
                error=str(e),
                exc_info=True
            )
            self._last_attempt = time.time()
            return False

        self._client = client
        self._available = True
        self._last_attempt = time.time()

        self.logger.info("Redis connection restored.")
        return True


    # ------------------------------------------------------------------
    # Unified execution helpers with error handling
    # ------------------------------------------------------------------
    def _execute_read(self, operation):
        """
        Execute a Redis read operation; return result on success, None on failure.

        This helper ensures the application does not crash if Redis is down.

        The live client is handed to the operation rather than captured by
        the caller: a bound method such as ``self._client.get`` would
        dereference the client while building the arguments, before this
        method runs, so a client set to None by an earlier failure would
        raise past all of this error handling.

        Args:
            operation: Callable taking the Redis client and returning a value.

        Returns:
            Result of the Redis call, or None if Redis is unavailable or an error occurs.
        """
        if not self._ensure_connection():
            return None
        try:
            return operation(self._client)
        except redis.ResponseError as e:
            # The server answered -- it just refused this command, typically
            # WRONGTYPE on a key someone else wrote. The connection is fine,
            # so dropping it here would disable the whole cache for a retry
            # interval because of one bad key.
            self.logger.error(
                "Redis rejected a read command",
                error=str(e),
                exc_info=True
            )
            return None
        except redis.RedisError as e:
            self.logger.error(
                "Redis read operation failed",
                error=str(e),
                exc_info=True
            )
            self._mark_unavailable()
            return None
    
    def _execute_write(self, operation) -> bool:
        """
        Execute a Redis write operation, reporting whether it happened.

        Takes the live client the same way ``_execute_read`` does, and for
        the same reason.

        Most callers ignore the result: on the request path a write that
        does not happen is a cache miss later, which is survivable. It is
        returned for the callers where silence is not survivable -- an
        invalidation that quietly does nothing leaves an entry describing a
        row that no longer exists.

        Args:
            operation: Callable taking the Redis client.

        Returns:
            ``True`` if Redis carried the command out.
        """
        if not self._ensure_connection():
            return False
        try:
            operation(self._client)
            return True
        except redis.ResponseError as e:
            # Rejected command, live connection -- see _execute_read.
            self.logger.error(
                "Redis rejected a write command",
                error=str(e),
                exc_info=True
            )
            return False
        except redis.RedisError as e:
            self.logger.error(
                "Redis write operation failed",
                error=str(e),
                exc_info=True
            )
            self._mark_unavailable()
            return False

    def _mark_unavailable(self) -> None:
        """
        Drop the client and start the reconnection back-off.

        Called when the connection itself failed, never for a command the
        server merely refused.
        """
        self._available = False
        self._client = None
        self._last_attempt = time.time()

    # ------------------------------------------------------------------
    # CacheHealth methods
    # ------------------------------------------------------------------
    def is_configured(self) -> bool:
        """
        Report that a real backend is configured.

        Always true for this implementation -- it is built around a Redis
        URL. Deliberately independent of whether a client object currently
        exists: a dropped client means Redis is down, not that the
        deployment chose to run without a cache, and conflating the two made
        a recovered Redis show up as "disabled".

        Returns:
            ``True``.
        """
        return True

    def ping(self) -> bool:
        """
        Probe Redis, reconnecting first if the client was dropped earlier.

        The probe goes through the same execute helper as every other
        operation, so its outcome updates the connection state: a failure
        marks the cache unavailable rather than leaving the "available" flag
        set from the last successful operation for the next caller to trust.

        Returns:
            ``True`` if Redis answered.
        """
        return bool(self._execute_read(lambda client: client.ping()))

    def close(self):
        """Close the Redis connection if open."""
        if self._client:
            self._client.close()
            self.logger.debug("Redis connection closed.")

    # ------------------------------------------------------------------
    # Signing helpers
    # ------------------------------------------------------------------
    def _seal(self, cache_key: str, payload: bytes) -> bytes:
        """
        Sign a payload for the key it is about to be stored under.

        Args:
            cache_key: Redis key the value belongs to.
            payload: Serialized value.

        Returns:
            Bytes to store.
        """
        return seal(self.secret_key, cache_key, payload)

    def _open(
        self, cache_key: str, blob: Optional[bytes], max_age: Optional[int] = None
    ) -> Optional[bytes]:
        """
        Recover a payload, refusing what this service did not write here
        and what it wrote too long ago.

        A refusal is reported as a miss rather than raised: the caller then
        asks the levels that can answer, which is what every other
        unusable value in this class already does.

        The age check is why the entry carries its own issue time. Redis
        enforces the TTL it was given, and whoever can write to Redis can
        give it a different one -- or none. An entry captured while it was
        legitimate and written back later resurrects what it described: a
        deleted link that redirects again, statistics frozen on an old
        count. The stamp is inside the signed message, so it cannot be
        pushed forward, and the lifetime is then ours rather than the
        cache server's.

        Args:
            cache_key: Redis key the value was read from.
            blob: Raw bytes from Redis.
            max_age: Oldest issue time still accepted, in seconds.

        Returns:
            The payload, or ``None``.
        """
        payload = unseal(self.secret_key, cache_key, blob, max_age_seconds=max_age)
        if blob and payload is None:
            # Worth a line: either somebody is writing to Redis directly, or
            # the deployment's SECRET_KEY changed and the whole cache is
            # about to be re-warmed. Both are things an operator wants to
            # know, and neither is visible any other way.
            self.logger.warning(
                "Refused a cache entry this service did not write",
                cache_key=cache_key,
            )
        return payload

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------
    def _serialize(self, link: Link) -> bytes:
        """
        Serialize a Link object to JSON bytes for Redis storage.

        Args:
            link: The Link entity to serialize.

        Returns:
            bytes: JSON representation encoded in UTF-8.
        """
        data = {
            "id": link.id,
            "url_hash": link.url_hash.value,
            "short_code": link.short_code.value,
            "original_url": link.original_url.value,
            "created_at": link.created_at.isoformat(),
            "clicks": link.clicks,
            "last_accessed": (
                link.last_accessed.isoformat() if link.last_accessed else None
            ),
            "owner_id": link.owner.value if link.owner else None,
            "expires_at": link.expires_at.isoformat() if link.expires_at else None,
            "guest_identifier": link.guest_identifier
        }
        return json.dumps(data).encode("utf-8")

    def _deserialize(self, data: bytes) -> Optional[Link]:
        """
        Deserialize JSON bytes back to a Link object.

        If the deserialized datetime fields are naive (missing timezone),
        they are automatically converted to timezone-aware UTC to match the
        domain model's expectations.

        Args:
            data: JSON bytes from Redis.

        Returns:
            Optional[Link]: The reconstructed Link object, or None if
                deserialization fails.
        """
        from datetime import datetime

        try:
            data_dict = json.loads(data.decode("utf-8"))

            created_at = datetime.fromisoformat(data_dict["created_at"])
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)

            last_accessed = None
            if data_dict.get("last_accessed"):
                last_accessed = datetime.fromisoformat(data_dict["last_accessed"])

                if last_accessed.tzinfo is None:
                    last_accessed = last_accessed.replace(tzinfo=timezone.utc)
            
            expires_at = None
            if data_dict.get("expires_at"):
                expires_at = datetime.fromisoformat(data_dict["expires_at"])
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)

            guest_identifier = data_dict.get("guest_identifier")

            return Link(
                id=data_dict["id"],
                url_hash=UrlHash(data_dict["url_hash"]),
                short_code=ShortCode(data_dict["short_code"]),
                original_url=OriginalUrl.from_storage(
                    data_dict["original_url"]
                ),
                created_at=created_at,
                clicks=data_dict["clicks"],
                last_accessed=last_accessed,
                owner=(
                    OwnerID(data_dict["owner_id"])
                    if data_dict.get("owner_id")
                    else None
                ),
                expires_at=expires_at,
                guest_identifier=guest_identifier
            )
        except Exception as e:
            self.logger.error(
                "Failed to deserialize cached link",
                error=str(e),
                exc_info=True
            )
            return None

    # ------------------------------------------------------------------
    # General methods
    # ------------------------------------------------------------------
    def get_cache_info(self) -> Dict[str, Any]:
        """Retrieve Redis server info (for monitoring)."""
        info = self._execute_read(lambda client: client.info())

        if info is None:
            return {"error": "Redis unavailable"}
        else:
            return {
                "used_memory": info.get("used_memory_human", "N/A"),
                "connected_clients": info.get("connected_clients", 0),
                "uptime": info.get("uptime_in_seconds", 0),
                "keyspace_hits": info.get("keyspace_hits", 0),
                "keyspace_misses": info.get("keyspace_misses", 0),
            }

    def clear_all(self) -> None:
        """Delete all keys with the configured prefix (dangerous)."""
        def _clear(client):
            pattern = f"{self.key_gen.prefix}:*"
            keys = client.keys(pattern)
            if keys:
                client.delete(*keys)
        self._execute_write(_clear)
    
    # ------------------------------------------------------------------
    # LinkCache methods
    # ------------------------------------------------------------------
    def get_by_code(self, short_code: ShortCode) -> Optional[Link]:
        """Retrieve a link by its short code."""

        key = self.key_gen.for_short_code(short_code.value)
        data = self._open(
            key, self._execute_read(lambda client: client.get(key)), self.ttl
        )

        return self._deserialize(data) if data else None

    def get_by_hash(
        self, url_hash: UrlHash, scope: DedupScope
    ) -> Optional[Link]:
        """Retrieve a link by its URL hash within one deduplication scope."""

        key = self.key_gen.for_url_hash(url_hash.value, scope.token())
        data = self._open(
            key, self._execute_read(lambda client: client.get(key)), self.ttl
        )

        return self._deserialize(data) if data else None

    def get_by_hashes(
        self, url_hashes: List[UrlHash], scope: DedupScope
    ) -> Dict[UrlHash, Optional[Link]]:
        """Retrieve multiple links by their URL hashes within one scope."""

        token = scope.token()
        keys = [self.key_gen.for_url_hash(h.value, token) for h in url_hashes]
        # A miss and an outage look the same to the caller: one entry per
        # requested hash. Returning an empty dict instead made this cache
        # disagree with NullCache and InMemoryLinkCache about its own
        # contract.
        data_list = self._execute_read(lambda client: client.mget(keys))
        if data_list is None:
            data_list = [None] * len(url_hashes)

        result = {}
        # Zipped with the keys as well as the hashes: each value is opened
        # against the key it was read from, so an entry copied onto another
        # hash's key does not verify.
        for url_hash, key, data in zip(url_hashes, keys, data_list):
            payload = self._open(key, data, self.ttl)
            result[url_hash] = self._deserialize(payload) if payload else None

        return result

    def _queue_link(self, pipeline, link: Link) -> None:
        """
        Add one link's three keys to a pipeline.

        Args:
            pipeline: Redis pipeline to append to.
            link: The link to store.
        """
        hash_key = self.key_gen.for_url_hash(
            link.url_hash.value, link.dedup_scope().token()
        )
        code_key = self.key_gen.for_short_code(link.short_code.value)
        redirect_key = self.key_gen.for_redirect(link.short_code.value)

        data = self._serialize(link)

        # Sealed once per key, not once per payload: the signature covers
        # the key, so the same bytes carry a different signature under each
        # of them and cannot be moved between the two.
        pipeline.setex(hash_key, self.ttl, self._seal(hash_key, data))
        pipeline.setex(code_key, self.ttl, self._seal(code_key, data))

        # The redirect entry is written through the same rules as
        # save_redirect: an envelope carrying the expiry, and a lifetime
        # capped at the link's own. Writing a bare URL on the full cache TTL
        # here is exactly how an expired link outlived its entity.
        redirect_ttl = self._redirect_ttl(link.expires_at)
        if redirect_ttl is not None:
            pipeline.setex(
                redirect_key,
                redirect_ttl,
                self._seal(
                    redirect_key,
                    self._serialize_redirect(
                        link.short_code.value,
                        link.original_url.value,
                        link.expires_at,
                    ),
                ),
            )

    def save(self, link: Link) -> None:
        """Store a link under multiple keys (hash, code, redirect) with TTL."""
        def _pipeline(client):
            pipeline = client.pipeline()
            self._queue_link(pipeline, link)
            pipeline.execute()
        self._execute_write(_pipeline)

    def save_many(self, links: List[Link]) -> None:
        """Bulk store multiple links."""

        if not links:
            return

        def _pipeline(client):
            pipeline = client.pipeline()

            for link in links:
                self._queue_link(pipeline, link)

            pipeline.execute()
        self._execute_write(_pipeline)

    def delete_by_code(self, short_code: ShortCode) -> bool:
        """Remove the two entries a code can name, for a link already gone.

        The hash entry stays: it is keyed by hash and scope, and neither is
        derivable from a code. It answers only deduplication lookups, and
        ``create_short_link`` confirms every hit against the database, so a
        survivor there costs a lookup rather than a wrong answer.

        Returns:
            ``True`` if Redis carried the deletion out.
        """
        keys = [
            self.key_gen.for_short_code(short_code.value),
            self.key_gen.for_redirect(short_code.value),
        ]
        return self._execute_write(lambda client: client.delete(*keys))

    def delete(self, link: Link) -> bool:
        """Remove every key written for a link.

        All three keys are named from the entity rather than discovered by
        reading the code entry, which leaves an orphan whenever that entry
        was evicted first -- and the orphan goes on answering deduplication
        lookups with a code that no longer resolves.

        Returns:
            ``True`` if Redis carried the deletion out.
        """

        keys = [
            self.key_gen.for_short_code(link.short_code.value),
            self.key_gen.for_redirect(link.short_code.value),
            self.key_gen.for_url_hash(
                link.url_hash.value, link.dedup_scope().token()
            ),
        ]
        return self._execute_write(lambda client: client.delete(*keys))

    def delete_redirect(self, short_code: ShortCode) -> None:
        """Remove only the redirect entry for a short code."""

        key = self.key_gen.for_redirect(short_code.value)
        self._execute_write(lambda client: client.delete(key))

    # ------------------------------------------------------------------
    # RedirectCache methods
    # ------------------------------------------------------------------
    def _redirect_ttl(self, expires_at: Optional[datetime]) -> Optional[int]:
        """
        Work out how long a redirect entry may live.

        Capped at the time left on the link itself, so an expired entry
        cannot outlive the link it points at -- it disappears by
        construction rather than by anyone remembering to check.

        Args:
            expires_at: When the link expires, or ``None`` if never.

        Returns:
            TTL in seconds, or ``None`` when the link has already expired
            and the entry must not be written at all.
        """
        if expires_at is None:
            return self.ttl

        remaining = (expires_at - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            return None

        # At least a second: SETEX rejects a zero TTL, and rounding a live
        # link down to nothing would drop a perfectly good entry.
        return max(1, min(self.ttl, int(remaining)))

    def _serialize_redirect(
        self, short_code: str, original_url: str, expires_at: Optional[datetime]
    ) -> bytes:
        """
        Encode a redirect entry.

        Args:
            short_code: The code the entry is written for.
            original_url: Destination URL.
            expires_at: Expiry of the link, or ``None``.

        Returns:
            JSON bytes.
        """
        return json.dumps(
            {
                "short_code": short_code,
                "url": original_url,
                "expires_at": expires_at.isoformat() if expires_at else None,
            }
        ).encode("utf-8")

    def _deserialize_redirect(
        self, data: bytes, short_code: ShortCode
    ) -> Optional[CachedRedirect]:
        """
        Decode a redirect entry, refusing anything it cannot vouch for.

        Every rejection below is a cache miss, never an error. A miss sends
        the request on to the levels that can answer; raising would turn a
        bad byte in Redis into a 500 on the redirect path.

        Refused: values that are not valid JSON objects -- which includes
        entries written in the old format, a bare URL string carrying no
        expiry, whose age cannot be judged; entries missing a field; and
        entries written for a different short code.

        Args:
            data: Raw value from Redis.
            short_code: The code being looked up.

        Returns:
            The decoded entry, or ``None``.
        """
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            # Either corruption, or the pre-envelope format: a bare URL is
            # not valid JSON. Both are unusable for the same reason -- there
            # is no expiry to check them against.
            return None

        if not isinstance(payload, dict):
            return None

        url = payload.get("url")
        stored_code = payload.get("short_code")
        if not isinstance(url, str) or not isinstance(stored_code, str):
            return None

        raw_expiry = payload.get("expires_at")
        expires_at = None
        if raw_expiry is not None:
            if not isinstance(raw_expiry, str):
                return None
            try:
                expires_at = datetime.fromisoformat(raw_expiry)
            except ValueError:
                return None
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

        entry = CachedRedirect(
            short_code=stored_code, original_url=url, expires_at=expires_at
        )

        # The value is bound to its key. An entry found under someone else's
        # code is not a redirect, it is a mix-up.
        if not entry.is_for(short_code):
            self.logger.error(
                "Redirect cache entry does not match its key",
                key=self.key_gen.for_redirect(short_code.value),
                stored_code=stored_code,
            )
            return None

        return entry

    def get_redirect(self, short_code: ShortCode) -> Optional[CachedRedirect]:
        """Retrieve the cached redirect for a short code (L1)."""

        key = self.key_gen.for_redirect(short_code.value)

        data = self._open(
            key, self._execute_read(lambda client: client.get(key)), self.ttl
        )
        if not data:
            return None

        return self._deserialize_redirect(data, short_code)

    def save_redirect(
        self,
        short_code: ShortCode,
        original_url: str,
        expires_at: Optional[datetime] = None,
    ) -> None:
        """Store a redirect entry, capped at the link's own lifetime."""

        ttl = self._redirect_ttl(expires_at)
        if ttl is None:
            # Already expired: writing it would only create something that
            # has to be refused on the way out.
            return

        key = self.key_gen.for_redirect(short_code.value)
        value = self._seal(
            key, self._serialize_redirect(short_code.value, original_url, expires_at)
        )
        self._execute_write(lambda client: client.setex(key, ttl, value))

    # ------------------------------------------------------------------
    # StatsCache methods
    # ------------------------------------------------------------------
    def get_stats(self) -> Optional[Dict[str, Any]]:
        """Retrieve cached service statistics."""

        key = self.key_gen.for_stats()

        data = self._open(
            key, self._execute_read(lambda client: client.get(key)), self.stats_ttl
        )
        if not data:
            return None

        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            # Same reasoning as the redirect cache: an unreadable entry is a
            # miss. The caller then rebuilds the stats from the database
            # instead of the error surfacing as fabricated zeroes.
            self.logger.error("Corrupted stats cache entry", key=key)
            return None

        # Shape is checked as well as signature: a JSON document that parses
        # but is not an object would reach the caller, which reads missing
        # fields as zeroes and publishes them.
        if not isinstance(payload, dict):
            self.logger.error("Stats cache entry is not an object", key=key)
            return None

        return payload

    def save_stats(self, stats: Dict[str, Any]) -> None:
        """Cache service statistics with TTL."""

        key = self.key_gen.for_stats()

        data = self._seal(key, json.dumps(stats).encode("utf-8"))

        self._execute_write(lambda client: client.setex(key, self.stats_ttl, data))

    def delete_stats(self) -> None:
        """Invalidate cached statistics."""

        key = self.key_gen.for_stats()
        self._execute_write(lambda client: client.delete(key))

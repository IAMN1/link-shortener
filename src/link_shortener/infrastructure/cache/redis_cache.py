"""
Redis-backed cache with automatic reconnection and graceful degradation.

Implements LinkCache, RedirectCache, and StatsCache. Falls back silently
when Redis is unavailable.
"""

from datetime import timezone
import json
import time
from typing import Any, Dict, List, Optional

from link_shortener.application import LinkCache, RedirectCache, StatsCache, Logger, CacheKeyBuilder
from link_shortener.domain import Link, OriginalUrl, ShortCode, UrlHash
from link_shortener.domain.value_objects.owner_id import OwnerID

import redis


class RedisLinkCache(LinkCache, RedirectCache, StatsCache):
    """
    Redis implementation of all three cache interfaces.

    Stores link data as JSON and uses pipelines for batch operations.
    Implements a reconnection strategy to tolerate transient Redis failures.
    """

    cache_type = "Redis"

    def __init__(
        self, redis_url: str, prefix: str, logger: Logger, link_ttl: int, 
        stats_ttl: int, connect_timeout: int, socket_timeout: int, retry_interval: int
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
        """
        self.redis_url = redis_url
        self.key_gen = CacheKeyBuilder(prefix=prefix)
        self.logger = logger
        self.ttl = link_ttl
        self.stats_ttl = stats_ttl
        self.connect_timeout = connect_timeout
        self.socket_timeout = socket_timeout
        self.retry_interval = retry_interval

        self.cache_type = "Redis"

        # Internal state for failover
        self._client = None
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
        Check if connection is alive; if not, attempt to reconnect.

        The method implements a simple backoff: reconnection is tried only
        after `retry_interval` seconds have passed since the last attempt.

        Returns:
            True if a working Redis connection is available, False otherwise
        """

        # If we have a client, test it with ping
        if self._client is not None:
            try:
                self._client.ping()
                self._available = True
                self._last_attempt = time.time()
                return True
            except redis.RedisError:
                self._available = False

        # If we already know it's unavailable, check retry interval
        if self._available:
            self._available = False
            self._last_attempt = time.time()
            return False

        # Attempt reconnection if enough time has passed
        if time.time() - self._last_attempt > self.retry_interval:
            try:
                self._client = redis.from_url(
                    self.redis_url, 
                    socket_connect_timeout=self.connect_timeout, 
                    socket_timeout=self.socket_timeout
                )
                self._client.ping()
                self._available = True
                self._last_attempt = time.time()

                self.logger.info("Redis connection restored.")
                return True
            
            except redis.RedisError as e:
                self.logger.error(
                    "Redis reconnection failed",
                    error=str(e),
                    exc_info=True
                )
                self._last_attempt = time.time()
                return False
        return False


    # ------------------------------------------------------------------
    # Unified execution helpers with error handling
    # ------------------------------------------------------------------
    def _execute_read(self, func, *args, **kwargs):
        """
        Execute a Redis read operation; return result on success, None on failure.

        This helper ensures the application does not crash if Redis is down.

        Args:
            func: Redis method to call (e.g., self._client.get).
            *args, **kwargs: Arguments to pass to the function.

        Returns:
            Result of the Redis call, or None if Redis is unavailable or an error occurs.
        """
        if not self._ensure_connection():
            return None
        try:
            return func(*args, **kwargs)
        except redis.RedisError as e:
            self.logger.error(
                "Redis read operation failed",
                error=str(e),
                exc_info=True
            )
            self._available = False
            self._client = None
            return None
    
    def _execute_write(self, func, *args, **kwargs):
        """
        Execute a Redis write operation; log errors but do not return a value.

        Args:
            func: Redis method or callable (e.g., self._client.setex, or a lambda).
            *args, **kwargs: Arguments to pass to the function.
        """
        if not self._ensure_connection():
            return
        try:
            func(*args, **kwargs)
        except redis.RedisError as e:
            self.logger.error(
                "Redis write operation failed",
                error=str(e),
                exc_info=True
            )
            self._available = False
            self._client = None
    
    def close(self):
        """Close the Redis connection if open."""
        if self._client:
            self._client.close()
            self.logger.debug("Redis connection closed.")

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
            "owner_id": link.owner.value if link.owner else None
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

            return Link(
                id=data_dict["id"],
                url_hash=UrlHash(data_dict["url_hash"]),
                short_code=ShortCode(data_dict["short_code"]),
                original_url=OriginalUrl(data_dict["original_url"]),
                created_at=created_at,
                clicks=data_dict["clicks"],
                last_accessed=last_accessed,
                owner=OwnerID(data_dict["owner_id"])
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
        info = self._execute_read(lambda: self._client.info())

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
        def _clear():
            pattern = f"{self.key_gen.prefix}:*"
            keys = self._client.keys(pattern)
            if keys:
                self._client.delete(*keys)
        self._execute_write(_clear)
    
    # ------------------------------------------------------------------
    # LinkCache methods
    # ------------------------------------------------------------------
    def get_by_code(self, short_code: ShortCode) -> Optional[Link]:
        """Retrieve a link by its short code."""

        key = self.key_gen.for_short_code(short_code.value)
        data = self._execute_read(self._client.get, key)

        return self._deserialize(data) if data else None

    def get_by_hash(self, url_hash: UrlHash) -> Optional[Link]:
        """Retrieve a link by its URL hash."""

        key = self.key_gen.for_url_hash(url_hash.value)
        data = self._execute_read(self._client.get, key)

        return self._deserialize(data) if data else None

    def get_by_hashes(self, url_hashes: List[UrlHash]) -> Dict[UrlHash, Optional[Link]]:
        """Retrieve multiple links by their URL hashes."""

        keys = [self.key_gen.for_url_hash(h.value) for h in url_hashes]
        data_list = self._execute_read(self._client.mget, keys) or []

        result = {}
        for url_hash, data in zip(url_hashes, data_list):
            result[url_hash] = self._deserialize(data) if data else None

        return result

    def save(self, link: Link) -> None:
        """Store a link under multiple keys (hash, code, redirect) with TTL."""
        def _pipeline():
            # Сохраняем по нескольким ключам для быстрого поиска
            hash_key = self.key_gen.for_url_hash(link.url_hash.value)
            code_key = self.key_gen.for_short_code(link.short_code.value)
            redirect = self.key_gen.for_redirect(link.short_code.value)

            data = self._serialize(link)

            pipeline = self._client.pipeline()
            
            pipeline.setex(hash_key, self.ttl, data)
            pipeline.setex(code_key, self.ttl, data)
            pipeline.setex(redirect, self.ttl, link.original_url.value)
            
            pipeline.execute()
        self._execute_write(_pipeline)

    def save_many(self, links: List[Link]) -> None:
        """Bulk store multiple links."""

        if not links:
            return

        def _pipeline():
            pipeline = self._client.pipeline()

            for link in links:
                hash_key = self.key_gen.for_url_hash(link.url_hash.value)
                code_key = self.key_gen.for_short_code(link.short_code.value)
                redirect_key = self.key_gen.for_redirect(link.short_code.value)

                data = self._serialize(link)

                pipeline.setex(hash_key, self.ttl, data)
                pipeline.setex(code_key, self.ttl, data)
                pipeline.setex(redirect_key, self.ttl, link.original_url.value)

            pipeline.execute()
        self._execute_write(_pipeline)

    def delete(self, short_code: ShortCode) -> None:
        """Remove a link and its associated keys from cache."""
        
        def _delete():
            code_key = self.key_gen.for_short_code(short_code.value)
            redirect_key = self.key_gen.for_redirect(short_code.value)

            # try to get link to find hash key
            data = self._client.get(code_key)
            keys_to_delete = [code_key, redirect_key]
            if data:
                link = self._deserialize(data)
                if link:
                    keys_to_delete.append(
                        self.key_gen.for_url_hash(
                            link.url_hash.value
                        )
                    )
            self._client.delete(*keys_to_delete)

        self._execute_write(_delete)

    # ------------------------------------------------------------------
    # RedirectCache methods
    # ------------------------------------------------------------------
    def get_original_url(self, short_code: ShortCode) -> Optional[str]:
        """Retrieve original URL from redirect cache (L1)."""

        key = self.key_gen.for_redirect(short_code.value)
        
        data = self._execute_read(self._client.get, key)

        return data.decode("utf-8") if data else None

    def save_original_url(self, short_code: ShortCode, original_url: str) -> None:
        """Store original URL in redirect cache with TTL."""
        
        key = self.key_gen.for_redirect(short_code.value)
        self._execute_write(self._client.setex, key, self.ttl, original_url)

    # ------------------------------------------------------------------
    # StatsCache methods
    # ------------------------------------------------------------------
    def get_stats(self) -> Optional[Dict[str, Any]]:
        """Retrieve cached service statistics."""

        key = self.key_gen.for_stats()
        
        data = self._execute_read(self._client.get, key)

        return json.loads(data.decode("utf-8")) if data else None

    def save_stats(self, stats: Dict[str, Any]) -> None:
        """Cache service statistics with TTL."""

        key = self.key_gen.for_stats()
        
        data = json.dumps(stats)
        
        self._execute_write(self._client.setex, key, self.stats_ttl, data)

    def delete_stats(self) -> None:
        """Invalidate cached statistics."""

        key = self.key_gen.for_stats()
        self._execute_write(self._client.delete, key)

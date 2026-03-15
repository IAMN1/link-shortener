from datetime import timezone
import json
import time
from typing import Any, Dict, List, Optional

from link_shortener.application import LinkCache, RedirectCache, StatsCache
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.domain import Link, OriginalUrl, ShortCode, UrlHash
from link_shortener.infrastructure.cache.cache_key_generator import CacheKeyGenerator
import redis


class RedisLinkCache(LinkCache, RedirectCache, StatsCache):
    """
    Redis implementation of all cache interfaces.

    This cache uses Redis for distributed caching with TTL support.
    It includes automatic reconnection logic and graceful degradation
    (returns None on Redis failures). When deserializing cached Link objects,
    any naive datetime fields are automatically converted to timezone-aware UTC
    to ensure consistency with domain entities.

    Cache key patterns:
        - Redirect: {prefix}:redirect:{short_code}
        - Link by code: {prefix}:code:{short_code}
        - Link by hash: {prefix}:hash:{url_hash}
        - Stats: {prefix}:stats:global
    """

    def __init__(
        self, redis_url: str, prefix: str, logger: Logger, link_ttl: int, 
        stats_ttl: int, connect_timeout: int, socket_timeout: int, retry_interval: int
    ):
        """
        Initialize Redis cache.

        Args:
            redis_url: Redis connection URL.
            prefix: Prefix for cache keys.
            logger: Logger instance for logging errors and info.
            link_ttl: TTL in seconds for link entries.
            stats_ttl: TTL in seconds for stats entries.
            connect_timeout: Socket connect timeout (seconds).
            socket_timeout: Socket read/write timeout (seconds).
            retry_interval: Seconds to wait before reconnection attempt after failure.
        """
        self.redis_url = redis_url
        self.key_gen = CacheKeyGenerator(prefix=prefix)
        self.logger = logger
        self.ttl = link_ttl
        self.stats_ttl = stats_ttl
        self.connect_timeout = connect_timeout
        self.socket_timeout = socket_timeout
        self.retry_interval = retry_interval

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
            
            self.logger.info(
                "Redis connected successfully."
            )
        except redis.RedisError as e:
            self.logger.error(
                f"Redis connection failed: {e}. Running without cache."
            )
            self._available = False
            self._client = None
    
    def _ensure_connection(self) -> bool:
        """
        Check if connection is alive; if not, attempt to reconnect after retry interval.

        Returns:
            True if connection is available, False otherwise.
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
            
            except redis.RedisError:
                self._last_attempt = time.time()
                return False
        return False

    def _execute(self, func, *args, **kwargs):
        """
        Execute a Redis operation; return None on failure.

        This wrapper ensures the application does not crash if Redis is down.
        """
        if not self._ensure_connection():
            return None
        try:
            return func(*args, **kwargs)
        except redis.RedisError as e:
            
            self.logger.error(f"Redis operation failed: {e}")
            
            self._available = False
            self._client = None
            return None

    def close(self):
        """Close the Redis connection."""
        if self._client:
            self._client.close()

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
            )
        except Exception as e:
            self.logger.error(f"Failed to deserialize cached link: {e}", exc_info=True)
            return None

    # ------------------------------------------------------------------
    # General methods
    # ------------------------------------------------------------------
    def get_cache_info(self) -> Dict[str, Any]:
        """Retrieve Redis server info (for monitoring)."""
        info = self._execute(lambda: self._client.info())

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

    # ------------------------------------------------------------------
    # LinkCache methods
    # ------------------------------------------------------------------
    def get_by_code(self, short_code: ShortCode) -> Optional[Link]:
        """Retrieve a link by its short code."""

        key = self.key_gen.for_short_code(short_code.value)
        data = self._execute(self._client.get, key)

        return self._deserialize(data) if data else None

    def get_by_hash(self, url_hash: UrlHash) -> Optional[Link]:
        """Retrieve a link by its URL hash."""

        key = self.key_gen.for_url_hash(url_hash.value)
        data = self._execute(self._client.get, key)

        return self._deserialize(data) if data else None

    def get_by_hashes(self, url_hashes: List[UrlHash]) -> Dict[UrlHash, Optional[Link]]:
        """Retrieve multiple links by their URL hashes."""

        keys = [self.key_gen.for_url_hash(h.value) for h in url_hashes]
        data_list = self._execute(self._client.mget, keys) or []

        result = {}
        for url_hash, data in zip(url_hashes, data_list):
            result[url_hash] = self._deserialize(data) if data else None

        return result

    def save(self, link: Link) -> None:
        """Store a link under multiple keys (hash, code, redirect) with TTL."""

        if not self._ensure_connection():
            return
        try:
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
        
        except redis.RedisError as e:
            self.logger.error(f"Redis save failed: {e}")
            self._available = False

    def save_many(self, links: List[Link]) -> None:
        """Bulk store multiple links."""

        if not links or not self._ensure_connection():
            return
        
        try:
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

        except redis.RedisError as e:
            self.logger.error(f"Redis save_many failed: {e}")
            self._available = False

    def delete(self, short_code: ShortCode) -> None:
        """Remove a link and its associated keys from cache."""

        if not self._ensure_connection():
            return
        
        try:
            code_key = self.key_gen.for_short_code(short_code.value)
            redirect_key = self.key_gen.for_redirect(short_code.value)

            # try to get link to find hash key
            data = self._execute(self._client.get, code_key)
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
        except redis.RedisError as e:
            self.logger.error(f"Redis delete failed: {e}")
            self._available = False

    # ------------------------------------------------------------------
    # RedirectCache methods
    # ------------------------------------------------------------------
    def get_original_url(self, short_code: ShortCode) -> Optional[str]:
        """Retrieve original URL from redirect cache (L1)."""

        key = self.key_gen.for_redirect(short_code.value)
        
        data = self._execute(self._client.get, key)

        return data.decode("utf-8") if data else None

    def save_original_url(self, short_code: ShortCode, original_url: str) -> None:
        """Store original URL in redirect cache with TTL."""

        if not self._ensure_connection():
            return
        
        try:
            key = self.key_gen.for_redirect(short_code.value)
            self._client.setex(key, self.ttl, original_url)
        except redis.RedisError as e:
            self.logger.error(
                f"Redis save_original_url failed: {e}"
            )
            
            self._available = False

    # ------------------------------------------------------------------
    # StatsCache methods
    # ------------------------------------------------------------------
    def get_stats(self) -> Optional[Dict[str, Any]]:
        """Retrieve cached service statistics."""

        key = self.key_gen.for_stats()
        
        data = self._execute(self._client.get, key)

        return json.loads(data.decode("utf-8")) if data else None

    def save_stats(self, stats: Dict[str, Any]) -> None:
        """Cache service statistics with TTL."""

        if not self._ensure_connection():
            return
        
        try:
            key = self.key_gen.for_stats()
            
            data = json.dumps(stats)
            
            self._client.setex(key, self.stats_ttl, data)

        except redis.RedisError as e:
            self.logger.error(f"Redis save_stats failed: {e}")
            self._available = False

    def delete_stats(self) -> None:
        """Invalidate cached statistics."""

        if not self._ensure_connection():
            return
        
        try:
            key = self.key_gen.for_stats()
            self._client.delete(key)

        except redis.RedisError as e:
            self.logger.error(f"Redis delete_stats failed: {e}")
            self._available = False

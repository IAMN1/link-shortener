from typing import Optional
from link_shortener.application import LinkCache, Logger
from link_shortener.infrastructure.cache.memory_cache import InMemoryLinkCache
from link_shortener.infrastructure.cache.null_cache import NullCache
from link_shortener.infrastructure.cache.redis_cache import RedisLinkCache


class CacheComponent:
    """
    Creates a singleton cache instance that implements ``LinkCache``,
    ``RedirectCache``, and ``StatsCache``.

    The actual implementation is chosen at first access:
    - **NullCache** if caching is globally disabled.
    - **RedisLinkCache** if Redis is enabled (falls back to NullCache on
      connection failure).
    - **InMemoryLinkCache** otherwise (development).
    """
    def __init__(self,
                 cache_enabled: bool,
                 redis_enabled: bool,
                 redis_url: str,
                 link_prefix: str,
                 link_ttl: int,
                 stats_ttl: int,
                 connect_timeout: int,
                 socket_timeout: int,
                 retry_interval: int,
                 logger: Logger,
                 secret_key: str):
        """
        Args:
            cache_enabled: Global toggle; if False, NullCache is used.
            redis_enabled: If True, attempt to use Redis.
            redis_url: Redis connection URL.
            link_prefix: Prefix for cache key namespacing.
            link_ttl: TTL for link entries (seconds).
            stats_ttl: TTL for stats entries (seconds).
            connect_timeout: Redis connection timeout (seconds).
            socket_timeout: Redis socket timeout (seconds).
            retry_interval: Seconds between reconnection attempts.
            logger: Application logger.
            secret_key: Key the Redis cache signs its values with.
        """
        
        self.secret_key = secret_key
        self.cache_enabled = cache_enabled
        self.redis_enabled = redis_enabled
        self.redis_url = redis_url
        self.link_prefix = link_prefix
        self.link_ttl = link_ttl
        self.stats_ttl = stats_ttl
        self.connect_timeout = connect_timeout
        self.socket_timeout = socket_timeout
        self.retry_interval = retry_interval
        self.logger = logger
        # Annotated Optional rather than inferred from this assignment: the
        # attribute holds None until the first call builds it, and a checker
        # told otherwise reports both the assignment and the return as errors.
        self._cache: Optional[LinkCache] = None

    def get_cache(self) -> LinkCache:
        """
        Return the singleton cache instance.

        The implementation is chosen based on the configuration flags.
        If Redis is enabled but the connection fails, a warning is logged
        and a ``NullCache`` is returned as a safe fallback.

        Returns:
            An object that implements ``LinkCache``, ``RedirectCache``,
            and ``StatsCache``.
        """
        if self._cache is None:
            if not self.cache_enabled:
                self.logger.warning("Cache disabled. Using NullCache.")
                self._cache = NullCache()
            elif self.redis_enabled:
                try:
                    self._cache = RedisLinkCache(
                        redis_url=self.redis_url,
                        prefix=self.link_prefix,
                        logger=self.logger,
                        link_ttl=self.link_ttl,
                        stats_ttl=self.stats_ttl,
                        connect_timeout=self.connect_timeout,
                        socket_timeout=self.socket_timeout,
                        retry_interval=self.retry_interval,
                        secret_key=self.secret_key,
                    )
                except Exception as e:
                    self.logger.error("Failed to init Redis cache. Falling back to NullCache.", error=str(e), exc_info=True)
                    self._cache = NullCache()
            else:
                self.logger.info("Using in-memory cache (development).")
                self._cache = InMemoryLinkCache(
                    prefix=self.link_prefix,
                    link_ttl=self.link_ttl,
                    stats_ttl=self.stats_ttl
                )
        return self._cache

    def close(self):
        """Release resources held by the cache (e.g., Redis connection)."""
        if self._cache and hasattr(self._cache, 'close'):
            self._cache.close()

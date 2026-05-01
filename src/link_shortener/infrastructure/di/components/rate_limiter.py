import redis
from link_shortener.application import RateLimiter
from link_shortener.infrastructure.rate_limit.memory_rate_limiter import MemoryRateLimiter
from link_shortener.infrastructure.rate_limit.redis_rate_limiter import RedisRateLimiter

class RateLimiterComponent:
    """
    Provides a singleton ``RateLimiter`` instance.

    If Redis is enabled, a ``RedisRateLimiter`` is created; otherwise a
    thread-safe in-memory limiter is used.
    """
    def __init__(self, redis_enabled: bool, redis_url: str):
        """
        Args:
            redis_enabled: If True, use Redis-backed rate limiting.
            redis_url: Redis connection URL.
        """
        self.redis_enabled = redis_enabled
        self.redis_url = redis_url
        self._limiter = None

    def get_rate_limiter(self) -> RateLimiter:
        """
        Return the configured rate limiter.

        On first call, the implementation is chosen based on
        ``redis_enabled``.

        Returns:
            A ``RateLimiter`` instance.
        """
        if self._limiter is None:
            if self.redis_enabled:
                redis_client = redis.from_url(self.redis_url)
                self._limiter = RedisRateLimiter(redis_client)
            else:
                self._limiter = MemoryRateLimiter()
        return self._limiter

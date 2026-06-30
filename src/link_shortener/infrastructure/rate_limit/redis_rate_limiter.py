import time
from link_shortener.application import RateLimiter
import redis


class RedisRateLimiter(RateLimiter):
    """
    Redis-backed rate limiter using a sliding window with sorted sets.

    The implementation uses a Lua script to atomically remove expired entries,
    count current requests, and add a new one if the limit is not exceeded.
    This is suitable for distributed environments (multiple workers) and
    provides high accuracy.

    Keys are stored as Redis sorted sets, where each member's score is the
    request timestamp. The TTL is set to the window length to automatically
    clean up abandoned keys.
    """

    def __init__(self, redis_client: redis.Redis, prefix: str = "rate_limiter"):
        """
        Args:
            redis_client: An authenticated Redis client.
            prefix: Prefix for Redis keys (default ``"rate_limiter"``).
        """
        self.redis = redis_client
        self.prefix = prefix
    
    def _get_key(self, key: str) -> str:
        """Return the full Redis key by prefixing the given identifier."""
        return f"{self.prefix}:{key}"
    
    def is_allowed(self, key, limit, period) -> bool:
        """
        Check if a request is allowed using an atomic Lua script.

        Args:
            key: Client identifier (e.g., IP address or user ID).
            limit: Maximum number of allowed requests in the window.
            period: Window length in seconds.

        Returns:
            True if the request is allowed, False otherwise.
        """
        redis_key = self._get_key(key)
        now = time.time()
        window_start = now - period

        # Lua script for atomicity.
        lua_script = """
        local key = KEYS[1]
        local now = tonumber(ARGV[1])
        local window_start = tonumber(ARGV[2])
        local limit = tonumber(ARGV[3])
        local ttl = tonumber(ARGV[4])

        -- Remove outdated requests
        redis.call('ZREMRANGEBYSCORE', key, 0, window_start)

        -- Count remaining requests
        local current = redis.call('ZCARD', key)

        if current < limit then
            -- Add current request with score = now and a unique member
            redis.call('ZADD', key, now, now .. ':' .. math.random())
            redis.call('EXPIRE', key, ttl)
            return 1
        else
            return 0
        end
        """
        allowed = self.redis.eval(
            lua_script,
            1,               # number of keys
            redis_key,       # KEYS[1]
            now,             # ARGV[1]
            window_start,    # ARGV[2]
            limit,           # ARGV[3]
            period           # ARGV[4]
        )
        return bool(allowed)
    
    def get_remaining(self, key, limit, period) -> int:
        """
        Return the number of remaining requests allowed in the current window.

        This method is not atomic and is intended only for reporting headers.

        Args:
            key: Client identifier.
            limit: Maximum requests per period.
            period: Window length in seconds.

        Returns:
            Non-negative integer representing remaining quota.
        """
        redis_key = self._get_key(key)
        now = time.time()
        window_start = now - period
        self.redis.zremrangebyscore(redis_key, 0, window_start)
        current = self.redis.zcard(redis_key)
        return max(0, limit - current)

from typing import Optional
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
    def __init__(
        self,
        redis_enabled: bool,
        redis_url: str,
        connect_timeout: int = 5,
        socket_timeout: int = 5,
        logger=None,
        retry_interval: int = 10,
    ):
        """
        Args:
            redis_enabled: If True, use Redis-backed rate limiting.
            redis_url: Redis connection URL.
            connect_timeout: Seconds to wait when opening the connection.
            socket_timeout: Seconds to wait for a reply.
            logger: Application logger for diagnostics.
            retry_interval: Seconds the limiter stops calling Redis for
                after the connection fails. Shares the value with the cache
                and the task queue: all three back off from the same Redis.
        """
        self.redis_enabled = redis_enabled
        self.redis_url = redis_url
        self.connect_timeout = connect_timeout
        self.socket_timeout = socket_timeout
        self.logger = logger
        self.retry_interval = retry_interval
        # Annotated Optional rather than inferred from this assignment: the
        # attribute holds None until the first call builds it, and a checker
        # told otherwise reports both the assignment and the return as errors.
        self._limiter: Optional[RateLimiter] = None

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
                # Timeouts are not optional here. This client runs in
                # ``before_request`` for every route, so a Redis that accepts
                # the connection and then never answers -- blackholed,
                # overloaded, failing over -- would otherwise block each
                # worker indefinitely, taking the whole service down along
                # with the healthcheck meant to notice.
                redis_client = redis.from_url(
                    self.redis_url,
                    socket_connect_timeout=self.connect_timeout,
                    socket_timeout=self.socket_timeout,
                )
                self._limiter = RedisRateLimiter(
                    redis_client,
                    logger=self.logger,
                    retry_interval=self.retry_interval,
                )
            else:
                self._limiter = MemoryRateLimiter()
        return self._limiter

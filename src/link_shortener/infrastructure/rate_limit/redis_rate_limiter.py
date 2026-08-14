import time
from threading import Lock
from typing import Optional

from link_shortener.application import RateLimiter, Logger
from link_shortener.application.ports.rate_limiter import RateLimitDecision
import redis


SLIDING_WINDOW_SCRIPT = """
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
    return {1, limit - current - 1}
else
    return {0, 0}
end
"""
"""
Sliding-window check, evaluated atomically on the server.

Returns the verdict *and* the remaining quota, because the caller needs
both and a second round trip for the second answer is one the request pays
for on every single route.
"""


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

    When Redis is unreachable the limiter fails **open**: requests are
    allowed. It runs in ``before_request`` for every route, so raising
    there would turn a cache outage into a 500 on every endpoint --
    including the health endpoints whose job is to report that outage.

    Failing open is not the same as failing quietly, and the two failures
    it can meet are not the same either:

    * The connection broke. Nothing can be enforced until it comes back,
      so the limiter backs off rather than paying a socket timeout on
      every request.
    * The server answered and refused the command: ``READONLY`` on a
      replica after a failover, ``OOM``, a rotated password. The
      connection is fine and the deployment is misconfigured, so dropping
      the connection would not help -- and ``PING`` is allowed in exactly
      these states, so no health surface would notice on its own.

    Either way ``is_enforcing()`` turns false, so the state is reportable
    instead of invisible.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        prefix: str = "rate_limiter",
        logger: Optional[Logger] = None,
        retry_interval: int = 10,
    ):
        """
        Args:
            redis_client: An authenticated Redis client.
            prefix: Prefix for Redis keys (default ``"rate_limiter"``).
            logger: Application logger for diagnostics.
            retry_interval: Seconds to stop calling Redis for after the
                connection fails, before trying it again.
        """
        self.redis = redis_client
        self.prefix = prefix
        self.logger = logger
        self.retry_interval = retry_interval

        self._lock = Lock()
        self._unreachable_since: Optional[float] = None
        self._refused = False

    def _backing_off(self) -> bool:
        """
        Report whether Redis is currently being skipped after a failure.

        A pure read: asking about the limiter's state must not declare the
        outage over, or the health check would report limits as enforced
        during an outage it had itself just erased. The outage is cleared
        in one place only -- a real operation that succeeded.

        Returns:
            True while the back-off window is still running.
        """
        if self._unreachable_since is None:
            return False

        return time.monotonic() - self._unreachable_since < self.retry_interval

    def _claim_attempt(self) -> bool:
        """
        Decide, once per interval, which caller retries Redis.

        Without this every thread that arrives while Redis is unreachable
        sees the window open and dials it, each paying the full socket
        timeout. The winner stamps the clock *before* trying, so the losers
        see a closed window and return immediately instead of queueing
        behind an outage.

        Returns:
            True if this caller should attempt the operation.
        """
        with self._lock:
            if self._unreachable_since is None:
                return True
            if self._backing_off():
                return False

            # Claim the retry for this caller.
            self._unreachable_since = time.monotonic()
            return True

    def is_enforcing(self) -> bool:
        """
        Report whether the configured limits are currently being applied.

        Probes Redis rather than reporting a remembered state. A remembered
        state is wrong in both directions: it would keep claiming an outage
        long after Redis returned, and -- before the back-off stopped being
        cleared by its own reader -- it claimed everything was fine during
        one.

        Known limit, stated rather than hidden: a server that answers
        ``PING`` but refuses writes (a read-only replica, ``OOM``) is only
        discovered by a real request, so ``_refused`` stays until traffic
        reveals it.

        Returns:
            ``False`` while Redis is unreachable or refusing commands.
        """
        if self._refused:
            return False

        if self._backing_off():
            # Requests are being waved through right now, by definition.
            return False

        try:
            self.redis.ping()
        except redis.RedisError:
            return False

        return True

    def _note_success(self) -> None:
        """Record that Redis answered, clearing any failure state.

        The only place an outage is cleared. Anything else would be
        declaring recovery without evidence of it.
        """
        with self._lock:
            self._unreachable_since = None
            self._refused = False

    def _note_refusal(self, error: Exception) -> None:
        """
        Record that a live server refused the command.

        The connection is healthy, so it is kept; only the fact that limits
        are not being applied is remembered.

        Args:
            error: The refusal returned by Redis.
        """
        with self._lock:
            self._refused = True
        if self.logger:
            self.logger.error(
                "Rate limiter cannot write, requests are not being throttled",
                error=str(error),
                reason="server refused the command",
            )

    def _note_outage(self, error: Exception) -> None:
        """
        Record that the connection failed and start the back-off.

        Args:
            error: The Redis failure that caused it.
        """
        with self._lock:
            self._unreachable_since = time.monotonic()
        self._report_outage(error)

    def check(self, key: str, limit: int, period: int) -> RateLimitDecision:
        """
        Decide on a request and report the remaining quota in one call.

        Args:
            key: Client identifier (e.g., IP address or user ID).
            limit: Maximum number of allowed requests in the window.
            period: Window length in seconds.

        Returns:
            The verdict and the remaining quota. When Redis cannot answer,
            the request is allowed and the full quota is reported -- there
            is no count to report, and understating it would throttle a
            client that was never measured.
        """
        if not self._claim_attempt():
            return RateLimitDecision(allowed=True, remaining=limit)

        try:
            allowed, remaining = self._evaluate(key, limit, period)
        except (redis.AuthenticationError, redis.ResponseError) as e:
            self._note_refusal(e)
            return RateLimitDecision(allowed=True, remaining=limit)
        except redis.RedisError as e:
            self._note_outage(e)
            return RateLimitDecision(allowed=True, remaining=limit)

        self._note_success()

        return RateLimitDecision(allowed=allowed, remaining=remaining)

    def _get_key(self, key: str) -> str:
        """Return the full Redis key by prefixing the given identifier."""
        return f"{self.prefix}:{key}"
    
    def _evaluate(self, key, limit, period):
        """
        Run the sliding-window script, atomically.

        Args:
            key: Client identifier.
            limit: Maximum number of allowed requests in the window.
            period: Window length in seconds.

        Returns:
            Tuple of (allowed, remaining).

        Raises:
            redis.RedisError: If Redis fails or refuses the command.
        """
        redis_key = self._get_key(key)
        now = time.time()
        window_start = now - period

        # One class in redis-py serves both the sync and the async client,
        # so ``eval`` is declared as returning an awaitable as well; this
        # client is the synchronous one and the script returns two numbers.
        allowed, remaining = self.redis.eval(  # type: ignore[misc]
            SLIDING_WINDOW_SCRIPT,
            1,               # number of keys
            redis_key,       # KEYS[1]
            now,             # ARGV[1]
            window_start,    # ARGV[2]
            limit,           # ARGV[3]
            period           # ARGV[4]
        )

        return bool(allowed), int(remaining)

    def is_allowed(self, key, limit, period) -> bool:
        """
        Check if a request is allowed using an atomic Lua script.

        Args:
            key: Client identifier (e.g., IP address or user ID).
            limit: Maximum number of allowed requests in the window.
            period: Window length in seconds.

        Returns:
            True if the request is allowed, False otherwise. Also True when
            Redis cannot be reached.
        """
        return self.check(key, limit, period).allowed

    def _report_outage(self, error: Exception) -> None:
        """
        Log that throttling is currently not being enforced.

        Args:
            error: The Redis failure that caused it.
        """
        if self.logger:
            self.logger.error(
                "Rate limiter unavailable, allowing request unthrottled",
                error=str(error),
            )
    
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
        if not self._claim_attempt():
            return limit

        redis_key = self._get_key(key)
        now = time.time()
        window_start = now - period
        try:
            self.redis.zremrangebyscore(redis_key, 0, window_start)
            current = self.redis.zcard(redis_key)
        except (redis.AuthenticationError, redis.ResponseError) as e:
            self._note_refusal(e)
            return limit
        except redis.RedisError as e:
            self._note_outage(e)
            return limit

        return max(0, limit - current)

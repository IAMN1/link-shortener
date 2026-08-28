from collections import defaultdict
from threading import RLock
import time
from link_shortener.application import RateLimiter


class MemoryRateLimiter(RateLimiter):
    """
    In-memory rate limiter using a fixed sliding window.

    This implementation stores timestamps of successful requests per key
    in a list. It is suitable for single-process environments (development,
    testing) but does not work correctly with multiple workers.

    Thread-safe via a reentrant lock.
    """

    def __init__(self):
        """Initialize the rate limiter with empty storage."""
        self._storage = defaultdict(list) # key -> list of timestamps
        self._lock = RLock()

    def is_allowed(self, key, limit, period) -> bool:
        """
        Check if a request is allowed and atomically record it.

        Args:
            key: Client identifier (e.g., IP or user ID).
            limit: Maximum number of requests allowed in the window.
            period: Window length in seconds.

        Returns:
            True if the request is within the limit, False otherwise.
        """
        with self._lock:
            now = time.time()
            window_start = now - period

            # Retain only timestamps within the current window.
            self._storage[key] = [ts for ts in self._storage[key] if ts > window_start]

            if len(self._storage[key]) < limit:
                self._storage[key].append(now)
                return True
            return False

    def get_remaining(self, key, limit, period) -> int:
        """
        Return the number of remaining requests allowed for the given key.

        Args:
            key: Client identifier.
            limit: Maximum requests per period.
            period: Window length in seconds.

        Returns:
            Non‑negative integer representing remaining quota.
        """
        with self._lock:
            now = time.time()
            window_start = now - period
            current = len([ts for ts in self._storage[key] if ts > window_start])
            return max(0, limit - current)

from abc import ABC, abstractmethod


class RateLimiter(ABC):
    """
    Abstract interface for rate limiting services.

    Defines the contract for checking request quotas and retrieving remaining
    capacity. Implementations may use different algorithms (sliding window,
    token bucket, etc.) and storage backends (Redis, in-memory, etc.).
    """
    @abstractmethod
    def is_allowed(self, key: str, limit: int, period: int) -> bool:
        """
        Check whether a request should be allowed.

        Args:
            key: Unique identifier for the client (e.g., IP address, user ID,
                 or a combination with endpoint). Used to isolate quotas.
            limit: Maximum number of allowed requests within the time period.
            period: Time window length in seconds.

        Returns:
            True if the request is within the quota, False otherwise.
        """
        pass

    @abstractmethod
    def get_remaining(self, key: str, limit: int, period: int) -> int:
        """Return the number of remaining requests allowed within the current window.

        Args:
            key: Unique identifier for the client.
            limit: Maximum requests per period.
            period: Time window length in seconds.

        Returns:
            Non-negative integer indicating how many more requests are permitted."""
        pass
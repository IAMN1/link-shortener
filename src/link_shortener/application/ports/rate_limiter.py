from abc import ABC, abstractmethod


class RateLimiter(ABC):
    """
    Abstract interface for rate limiting services.

    Allows checking whether a request is within the allowed quota,
    and retrieving remaining capacity.
    """
    @abstractmethod
    def is_allowed(self, key: str, limit: int, period: int) -> bool:
        """
        Check whether a request should be allowed.

        Args:
            key: Unique client identifier (IP, user ID, etc.).
            limit: Max requests allowed in the window.
            period: Window length in seconds.

        Returns:
            True if the request is within the quota.
        """
        ...

    @abstractmethod
    def get_remaining(self, key: str, limit: int, period: int) -> int:
        """
        Return the number of remaining requests in the current window.

        Args:
            key: Client identifier.
            limit: Max requests per window.
            period: Window length in seconds.

        Returns:
            Non-negative integer remaining.
        """
        ...

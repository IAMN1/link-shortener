from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitDecision:
    """
    The verdict on one request, plus what is left of its quota.

    Both answers come from the same observation. Asking for them separately
    meant a second round trip on every allowed request, purely to fill in a
    response header -- and against a backend that had stopped answering,
    that header cost a second full socket timeout.

    Attributes:
        allowed: Whether the request is within the quota.
        remaining: Requests still available in the current window.
    """

    allowed: bool
    remaining: int


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

    def check(self, key: str, limit: int, period: int) -> RateLimitDecision:
        """
        Decide on a request and report the remaining quota together.

        Implementations backed by a network service should override this to
        answer in a single round trip. The default spares implementations
        with nothing to gain from it -- the in-memory limiter -- from having
        to say so.

        Args:
            key: Client identifier.
            limit: Max requests per window.
            period: Window length in seconds.

        Returns:
            The verdict and the remaining quota.
        """
        allowed = self.is_allowed(key, limit, period)

        return RateLimitDecision(
            allowed=allowed, remaining=self.get_remaining(key, limit, period)
        )

    def is_enforcing(self) -> bool:
        """
        Report whether limits are actually being applied right now.

        A limiter that cannot reach its backend lets every request through,
        which is the right call for availability but leaves brute-force
        protection switched off. Doing so *silently* is the part that is
        not acceptable: this is what lets a health check say otherwise.

        Returns:
            ``True`` when the configured limits are in force.
        """
        return True

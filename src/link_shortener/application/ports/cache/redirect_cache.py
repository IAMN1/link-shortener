from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from link_shortener.domain import ShortCode


@dataclass(frozen=True)
class CachedRedirect:
    """
    A cached redirect that can answer for itself whether it may be served.

    Carrying the expiry alongside the URL is what makes an L1 hit a
    complete answer: a bare URL string cannot say whether the link has
    expired, so every hit would still have to consult L2, and the level
    would cost a round trip and save nothing.

    The expiry is deliberately redundant with the entry's TTL -- the TTL
    already caps the lifetime, but it is enforced by the cache server's
    clock, and the two clocks are not the same one.

    ``short_code`` is stored for the same reason: it binds the value to the
    key it was written under, so an entry that ends up under the wrong key
    is refused rather than served as a redirect to somewhere else.

    Attributes:
        short_code: The code this entry was written for.
        original_url: Destination to redirect to.
        expires_at: When the link expires; ``None`` for a permanent link.
    """

    short_code: str
    original_url: str
    expires_at: Optional[datetime]

    def is_expired(self) -> bool:
        """
        Check whether the cached link has expired.

        Mirrors ``Link.is_expired``: the entry is a projection of the entity
        and must answer the same question the same way.

        Returns:
            True if the expiration timestamp has passed.
        """
        if self.expires_at is None:
            return False

        return datetime.now(timezone.utc) >= self.expires_at

    def is_for(self, short_code: ShortCode) -> bool:
        """
        Check that this entry belongs to the code being looked up.

        Args:
            short_code: The code the caller asked about.

        Returns:
            True if the entry was written for that code.
        """
        return self.short_code == short_code.value


class RedirectCache(ABC):
    """
    Interface for caching original URLs for fast redirects (L1 cache).

    Stores just enough to complete a redirect without consulting any other
    level: the destination and the expiry that decides whether it may still
    be used.
    """

    @abstractmethod
    def get_redirect(self, short_code: ShortCode) -> Optional[CachedRedirect]:
        """
        Retrieve the cached redirect for a short code (fast path).

        Implementations must treat an entry they cannot vouch for as a miss
        rather than an error: an unreadable value, one written in an older
        format that carried no expiry, or one belonging to a different code.
        A miss sends the request on to the levels that can answer, which is
        always correct; anything else hands out a redirect on the strength
        of a value nobody can vouch for.

        Args:
            short_code: Short code value object.

        Returns:
            The cached redirect, or ``None`` if there is nothing usable.
        """
        ...

    @abstractmethod
    def save_redirect(
        self,
        short_code: ShortCode,
        original_url: str,
        expires_at: Optional[datetime] = None,
    ) -> None:
        """
        Store a redirect for a short code.

        The entry's own lifetime must not outlast the link's: implementations
        cap it at the time remaining until ``expires_at``. An already-expired
        link is not stored at all. That way an expired entry disappears by
        construction, and the expiry carried in the value is a second line
        of defence rather than the only one.

        Args:
            short_code: Short code value object.
            original_url: Original URL string.
            expires_at: When the link expires; ``None`` for a permanent link.
        """
        ...

    @abstractmethod
    def delete_redirect(self, short_code: ShortCode) -> None:
        """
        Remove the redirect entry for a short code.

        Named apart from ``LinkCache.delete`` on purpose: one object
        implements both ports, and the link cache needs the whole entity to
        find every key it wrote, while a redirect entry is named by its code
        and nothing else.

        Args:
            short_code (ShortCode): Short code value object.
        """
        ...

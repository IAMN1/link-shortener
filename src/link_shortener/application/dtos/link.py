from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from link_shortener.application.utils.url_utils import build_short_url
from link_shortener.domain import Link


@dataclass
class ShortLinkResponse:
    """
    Basic information about a short link.

    Attributes:
        short_code: The short code.
        short_url: Full short URL.
        original_url: The original long URL.
        clicks: Number of times the link has been accessed.
        created_at: Timestamp of creation.
        last_accessed: Timestamp of last access (if any).
        expires_at: When the link expires; ``None`` for a permanent one.
        is_new: True if the link was just created.
        from_cache: True if data came from cache.
        owner_id: Account the link belongs to, or ``None`` for a guest's.
            Internal: it is what the web layer reads to decide whether a
            deletion token is issued, and never goes into a response.
        link_id: Identifier of the stored row. Internal: the web layer signs
            it into the deletion token handed to a guest, and never puts it
            in a response.
    """
    short_code: str
    short_url: str
    original_url: str
    clicks: int
    created_at: datetime
    last_accessed: Optional[datetime]
    expires_at: Optional[datetime] = None
    is_new: bool = False
    from_cache: bool = False
    owner_id: Optional[str] = None
    link_id: Optional[str] = None

    @classmethod
    def from_link(
       cls, link: Link, base_url: str, is_new: bool = False, from_cache: bool = False 
    ) -> "ShortLinkResponse":
        """
        Construct DTO from a domain Link entity.

        Args:
            link: Domain entity.
            base_url: Base URL used to build the full short link.
            is_new: Whether the link is newly created.
            from_cache: Whether the link was fetched from cache.

        Returns:
            ShortLinkResponse.
        """
        short_url = build_short_url(base_url, link.short_code.value)
        return cls(
            short_code=str(link.short_code.value),
            short_url=short_url,
            original_url=str(link.original_url.value),
            clicks=link.clicks,
            created_at=link.created_at,
            last_accessed=link.last_accessed,
            expires_at=link.expires_at,
            is_new=is_new,
            from_cache=from_cache,
            owner_id=link.owner.value if link.owner else None,
            link_id=link.id,
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize to a dictionary (e.g., for caching).

        Returns:
            Dictionary with ISO-formatted dates.
        """
        return {
            "short_code": self.short_code,
            "short_url": self.short_url,
            "original_url": self.original_url,
            "clicks": self.clicks,
            "created_at": self.created_at.isoformat(),
            "last_accessed": (
                self.last_accessed.isoformat() if self.last_accessed else None
            ),
            "expires_at": (
                self.expires_at.isoformat() if self.expires_at else None
            ),
            "is_new": self.is_new,
            "from_cache": self.from_cache,
        }


@dataclass
class ExtendedLinkInfoResponse:
    """
    Extended link information including derived metrics.

    Attributes:
        short_code: Short code.
        short_url: Full short URL.
        original_url: Original URL.
        clicks: Total clicks.
        created_at: Creation timestamp.
        last_accessed: Last access timestamp.
        is_popular: Whether the link's clicks exceed the popular threshold.
        is_recent: Whether the link was created recently.
        age_days: Age of the link in days.
        clicks_per_day: Average clicks per day.
        last_access_days_ago: Days since last access (None if never accessed).
        owner_id: Account the link belongs to, or ``None`` for a guest's.
            Internal, as on ``ShortLinkResponse``: it never goes into a
            response.
    """
    short_code: str
    short_url: str
    original_url: str
    clicks: int
    created_at: datetime
    last_accessed: Optional[datetime]
    is_popular: bool
    is_recent: bool
    age_days: int
    clicks_per_day: float
    last_access_days_ago: Optional[int]
    owner_id: Optional[str] = None

    @classmethod
    def from_link(
        cls, link: Link, base_url: str,
        popular_threshold: int, recent_days: int
    ) -> "ExtendedLinkInfoResponse":
        """
        Construct DTO with derived metrics from a domain Link.

        Args:
            link: Domain entity.
            base_url: Base URL for the full short link.
            popular_threshold: Clicks threshold for 'popular'.
            recent_days: Maximum days to consider a link 'recent'.

        Returns:
            ExtendedLinkInfoResponse.
        """
        short_url = build_short_url(base_url, link.short_code.value)
        age_days = (datetime.now(timezone.utc) - link.created_at).days
        clicks_per_day = (
            round(link.clicks / max(age_days, 1), 2) if link.clicks > 0 else 0.0
        )
        last_access_days_ago = (
            (datetime.now(timezone.utc) - link.last_accessed).days
            if link.last_accessed else None
        )
        return cls(
            short_code=str(link.short_code.value),
            short_url=short_url,
            original_url=str(link.original_url.value),
            clicks=link.clicks,
            created_at=link.created_at,
            last_accessed=link.last_accessed,
            is_popular=link.is_popular(threshold=popular_threshold),
            is_recent=link.is_recent(days=recent_days),
            age_days=age_days,
            clicks_per_day=clicks_per_day,
            last_access_days_ago=last_access_days_ago,
            owner_id=link.owner.value if link.owner else None
        )

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from link_shortener.domain import Link


@dataclass
class ShortLinkResponse:
    """
    DTO for a short link response, used when a link is created or retrieved.

    Attributes:
        short_code: The generated short code.
        short_url: The full short URL (base URL + short code).
        original_url: The original long URL.        clicks: Number of times the link has been accessed.
        created_at: Timestamp when the link was created.
        last_accessed: Timestamp of the last access (if any).
        is_new: True if the link was just created in this request.
        from_cache: True if the data came from cache.
    """

    short_code: str
    short_url: str
    original_url: str
    clicks: int
    created_at: datetime
    last_accessed: Optional[datetime]
    is_new: bool = False
    from_cache: bool = False

    @classmethod
    def from_link(
        cls, link: Link, base_url: str, is_new: bool = False, from_cache: bool = False
    ) -> "ShortLinkResponse":
        """
        Create a DTO from a domain Link entity.

        Args:
            link: The domain Link object.
            base_url: Base URL of the service (e.g., "https://short.xyz").
            is_new: Whether this link was just created.
            from_cache: Whether the data came from cache.

        Returns:
            ShortLinkResponse instance.
        """

        short_url = f'{base_url.rstrip("/")}/{link.short_code.value}'

        return cls(
            short_code=str(link.short_code.value),
            short_url=short_url,
            original_url=str(link.original_url.value),
            clicks=link.clicks,
            created_at=link.created_at,
            last_accessed=link.last_accessed,
            is_new=is_new,
            from_cache=from_cache,
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the DTO to a dictionary for JSON serialization.

        Returns:
            Dictionary with ISO-formatted datetime strings.
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
            "is_new": self.is_new,
            "from_cache": self.from_cache,
        }


@dataclass
class BatchItemResponse:
    """
    DTO for a single item in a batch create response.

    Attributes:
        success: Whether processing this URL succeeded.
        url: The original URL provided in the request.
        short_code: Generated short code (if successful).
        original_url: Normalized original URL (may differ from input if duplicates).
        short_url: Full short URL (if successful).
        clicks: Current click count (if link existed).
        error: Error message (if failed).
        is_new: True if a new link was created.
        from_cache: True if data came from cache.
        duplicate_of: If this URL is a duplicate of another, contains the original URL.
        processing_time_ms: Optional processing time for this item.
    """

    success: bool
    url: str
    short_code: Optional[str] = None
    original_url: Optional[str] = None
    short_url: str
    clicks: int = 0
    error: Optional[str] = None
    is_new: bool = False
    from_cache: bool = False
    duplicate_of: Optional[str] = None
    processing_time_ms: Optional[float] = None

    @classmethod
    def success_(
        cls,
        url: str,
        short_code: str,
        original_url: str,
        base_url: str,
        clicks: int = 0,
        is_new: bool = False,
        from_cache: bool = False,
        duplicate_of: Optional[str] = None,
    ) -> "BatchItemResponse":
        """
        Factory method for a successful item.

        Args:
            url: Original input URL.
            short_code: Generated short code.
            original_url: Normalized original URL.
            base_url: Base URL for building short URL.
            clicks: Click count.
            is_new: Whether this is a new link.
            from_cache: Whether data came from cache.
            duplicate_of: If duplicate, the original URL it duplicates.

        Returns:
            BatchItemResponse with success=True.
        """
        short_url = f'{base_url.rstrip("/")}/{short_code}'
        return cls(
            url=url,
            success=True,
            short_code=short_code,
            original_url=original_url,
            short_url=short_url,
            clicks=clicks,
            is_new=is_new,
            from_cache=from_cache,
            duplicate_of=duplicate_of,
        )

    @classmethod
    def error_(cls, url: str, error: str) -> "BatchItemResponse":
        """
        Factory method for a failed item.

        Args:
            url: Original input URL.
            error: Error message.

        Returns:
            BatchItemResponse with success=False
        """
        return cls(success=False, url=url, error=error)


@dataclass
class BatchCreateResponse:
    """
    DTO for the entire batch create response, including aggregated statistics.

    Attributes:
        items: List of individual item responses.
        total: Total number of URLs processed.
        successful: Number of successful items.
        failed: Number of failed items.
        from_cache_count: Number of items served from cache.
        from_db_count: Number of items retrieved from database (not new).
        new_count: Number of newly created links.
        processing_time_seconds: Total processing time.
        created_at: Timestamp of the response creation.
    """

    items: List[BatchItemResponse]
    total: int = 0
    successful: int = 0
    failed: int = 0
    from_cache_count: int = 0
    from_db_count: int = 0
    new_count: int = 0
    processing_time_seconds: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)

    @classmethod
    def from_results(cls, results: List[BatchItemResponse]) -> "BatchCreateResponse":
        """
        Create a BatchCreateResponse by aggregating a list of item results.

        Args:
            results: List of BatchItemResponse objects.

        Returns:
            BatchCreateResponse with computed totals.
        """

        total = len(results)
        successful = sum(1 for r in results if r.success)
        failed = total - successful
        from_cache_count = sum(1 for r in results if r.from_cache)
        from_db_count = sum(
            1 for r in results if r.success and not r.is_new and not r.from_cache
        )
        new_count = sum(1 for r in results if r.is_new)

        return cls(
            items=results,
            total=total,
            successful=successful,
            failed=failed,
            from_cache_count=from_cache_count,
            from_db_count=from_db_count,
            new_count=new_count,
            created_at=datetime.now(),
        )

    @classmethod
    def empty(cls) -> "BatchCreateResponse":
        """Return an empty response (no items)."""
        return cls(items=[])


@dataclass
class StatsItemResponse:
    """
    DTO for a single item in service statistics (popular links).

        Attributes:
            short_code: Short code.
            short_url: Full short URL.
            original_url: Original URL.
            clicks: Click count.
            created_at: Creation timestamp.
    """

    short_code: str
    short_url: str
    original_url: str
    clicks: int
    created_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "short_code": self.short_code,
            "short_url": self.short_url,
            "original_url": self.original_url,
            "clicks": self.clicks,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class ServiceStatsResponse:
    """
    DTO for service-wide statistics.

    Attributes:
        total_urls: Total number of shortened URLs.
        total_clicks: Sum of all clicks across all links.
        avg_clicks_per_url: Average clicks per URL.
        popular_links: List of most popular links (up to 10).
    """

    total_urls: int
    total_clicks: int
    avg_clicks_per_url: float
    popular_links: List[StatsItemResponse]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "total_urls": self.total_urls,
            "total_clicks": self.total_clicks,
            "avg_clicks_per_url": round(self.avg_clicks_per_url, 2),
            "popular_links": [link.to_dict() for link in self.popular_links],
        }


@dataclass
class ExtendedLinkInfoResponse:
    """
    DTO for extended link information including derived metrics.

    Attributes:
        short_code: Short code.
        short_url: Full short URL.
        original_url: Original URL.
        clicks: Click count.
        created_at: Creation timestamp.
        last_accessed: Last access timestamp.
        is_popular: Whether the link is considered popular (based on threshold).
        is_recent: Whether the link was created recently.
        age_days: Age in days.
        clicks_per_day: Average clicks per day.
        last_access_days_ago: Days since last access (if any).
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

    @classmethod
    def from_link(cls, link: Link, base_url: str) -> "ExtendedLinkInfoResponse":
        """
        Create an extended DTO from a domain Link entity.

        Args:
            link: Domain Link object.
            base_url: Base URL of the service.

        Returns:
            ExtendedLinkInfoResponse with computed metrics.
        """

        short_url = f'{base_url.rstrip("/")}/{link.short_code.value}'

        age_days = (datetime.now() - link.created_at).days
        clicks_per_day = (
            round(link.clicks / max(age_days, 1), 2) if link.clicks > 0 else 0.0
        )
        last_access_days_ago = (
            (datetime.now() - link.last_accessed).days if link.last_accessed else None
        )

        return cls(
            short_code=str(link.short_code.value),
            short_url=short_url,
            original_url=str(link.original_url.value),
            clicks=link.clicks,
            created_at=link.created_at,
            last_accessed=link.last_accessed,
            is_popular=link.is_popular(),
            is_recent=link.is_recent(),
            age_days=age_days,
            clicks_per_day=clicks_per_day,
            last_access_days_ago=last_access_days_ago,
        )

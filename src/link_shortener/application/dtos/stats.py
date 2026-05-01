from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List

from link_shortener.application.utils.url_utils import build_short_url
from link_shortener.domain import Link


@dataclass
class StatsItemResponse:
    """
    Statistics for a single link.

    Attributes:
        short_code: The short code.
        short_url: Full short URL.
        original_url: Original URL.
        clicks: Number of clicks.
        created_at: Creation timestamp.
    """
    short_code: str
    short_url: str
    original_url: str
    clicks: int
    created_at: datetime

    @classmethod
    def from_link(cls, link: Link, base_url: str) -> "StatsItemResponse":
        """
        Create DTO from a domain Link.

        Args:
            link: Domain entity.
            base_url: Base URL for the full short link.

        Returns:
            StatsItemResponse.
        """
        return cls(
            short_code=str(link.short_code.value),
            short_url=build_short_url(base_url, link.short_code.value),
            original_url=str(link.original_url.value),
            clicks=link.clicks,
            created_at=link.created_at,
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize to dictionary (e.g., for caching).

        Returns:
            Dictionary with ISO date string.
        """
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
    Aggregated service statistics.

    Attributes:
        total_urls: Total number of URLs in the system.
        total_clicks: Total clicks across all URLs.
        avg_clicks_per_url: Average clicks per URL.
        popular_links: List of top links by clicks.
    """
    total_urls: int
    total_clicks: int
    avg_clicks_per_url: float
    popular_links: List[StatsItemResponse]

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize to dictionary.

        Returns:
            Dictionary with aggregated values and a list of popular links.
        """
        return {
            "total_urls": self.total_urls,
            "total_clicks": self.total_clicks,
            "avg_clicks_per_url": round(self.avg_clicks_per_url, 2),
            "popular_links": [link.to_dict() for link in self.popular_links],
        }

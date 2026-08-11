from datetime import datetime
from typing import List

from pydantic import BaseModel, ConfigDict, field_serializer

from link_shortener.web.schemas.link import ShortLinkResponse


class StatsItemResponse(BaseModel):
    """
    Statistics for a single popular link.

    Attributes:
        short_code: The short code.
        short_url: Full short URL.
        original_url: The original long URL.
        clicks: Number of recorded accesses.
        created_at: Creation timestamp.
    """

    short_code: str
    short_url: str
    original_url: str
    clicks: int
    created_at: datetime

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "short_code": "abc123",
                "short_url": "https://short.xyz/abc123",
                "original_url": "https://example.com/1",
                "clicks": 100,
                "created_at": "2026-02-20T12:00:00"
            }
        }
    )

    @field_serializer('created_at')
    def serialize_dt(self, value: datetime) -> str:
        """
        Serialize the creation timestamp to an ISO 8601 string.

        Args:
            value: A timezone-aware datetime.

        Returns:
            ISO-formatted string.
        """
        return value.isoformat()

    @classmethod
    def from_dto(cls, dto) -> "StatsItemResponse":
        """
        Build a schema instance from an application DTO.

        Args:
            dto: A ``StatsItemResponse`` DTO from the application layer.

        Returns:
            Populated ``StatsItemResponse`` schema instance.
        """
        return cls(
            short_code=dto.short_code,
            short_url=dto.short_url,
            original_url=dto.original_url,
            clicks=dto.clicks,
            created_at=dto.created_at
        )


class ServiceStatsResponse(BaseModel):
    """
    Aggregated service-wide statistics.

    Attributes:
        total_urls: Total number of short links in the system.
        total_clicks: Sum of all clicks across all links.
        avg_clicks_per_url: Average number of clicks per link.
        popular_links: List of the most popular links (up to 10).
    """

    total_urls: int
    total_clicks: int
    avg_clicks_per_url: float
    popular_links: List[StatsItemResponse]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total_urls": 1_000,
                "total_clicks": 15_000,
                "avg_clicks_per_url": 15.0,
                "popular_links": [
                    {
                        "short_code": "abc123",
                        "short_url": "https://short.xyz/abc123",
                        "original_url": "https://example.com/1",
                        "clicks": 100,
                        "created_at": "2026-02-20T12:00:00"
                    }
                ]
            }
        }
    )

    @classmethod
    def from_dto(cls, dto) -> "ServiceStatsResponse":
        """
        Build a schema instance from an application DTO.

        Args:
            dto: A ``ServiceStatsResponse`` DTO from the application layer.

        Returns:
            Populated ``ServiceStatsResponse`` schema instance.
        """
        return cls(
            total_urls=dto.total_urls,
            total_clicks=dto.total_clicks,
            avg_clicks_per_url=dto.avg_clicks_per_url,
            popular_links=[
                StatsItemResponse.from_dto(link)
                for link in dto.popular_links
            ]
        )


class MyStatsResponse(BaseModel):
    """
    What ``GET /api/v1/stats/mine`` answers.

    Named apart from ``ServiceStatsResponse`` because the two are not the
    same shape: this one counts links rather than URLs and carries the
    caller's most recent links whole, so a generated client that reused
    the service-wide schema would be reading fields that are not there.

    Attributes:
        total_links: Links this caller owns.
        total_clicks: Sum of clicks across them.
        avg_clicks_per_link: Average clicks per link, ``0.0`` with none.
        recent_links: Up to ten most recently created, as links.
    """

    total_links: int
    total_clicks: int
    avg_clicks_per_link: float
    recent_links: List[ShortLinkResponse]

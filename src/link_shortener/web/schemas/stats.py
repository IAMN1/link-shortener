from datetime import datetime
from typing import List

from pydantic import BaseModel, ConfigDict, field_serializer


class StatsItemResponse(BaseModel):
    """Statistics for a single popular link."""

    short_code: str
    short_url: str
    original_url: str
    clicks: int
    created_at: datetime

    @field_serializer('created_at')
    def serialize_dt(self, value: datetime) -> str:
        return value.isoformat()

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

    @classmethod
    def from_dto(cls, dto) -> "StatsItemResponse":
        return cls(
            short_code=dto.short_code,
            short_url=dto.short_url,
            original_url=dto.original_url,
            clicks=dto.clicks,
            created_at=dto.created_at
        )


class ServiceStatsResponse(BaseModel):
    """Aggregated service statistics"""

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
        return cls(
            total_urls=dto.total_urls,
            total_clicks=dto.total_clicks,
            avg_clicks_per_url=dto.avg_clicks_per_url,
            popular_links=[
                StatsItemResponse.from_dto(link)
                for link in dto.popular_links
            ]
        )

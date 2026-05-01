from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_serializer


class ShortLinkResponse(BaseModel):
    """Basic link information returned to clients."""

    short_code: str
    short_url: str
    original_url: str
    clicks: int
    created_at: datetime
    last_accessed: Optional[datetime]
    is_new: bool
    from_cache: bool

    @field_serializer('created_at', 'last_accessed')
    def serialize_dt(self, value: Optional[datetime]) -> Optional[str]:
        if value is None:
            return None
        return value.isoformat()

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "short_code": "abc123",
                "short_url": "https://short.xyz/abc123",
                "original_url": "https://example.com/very/long/url",
                "clicks": 42,
                "created_at": "2026-02-20T12:00:00",
                "last_accessed": "2026-02-20T15:30:00",
                "is_new": False,
                "from_cache": True
            }
        }
    )

    @classmethod
    def from_dto(cls, dto) -> 'ShortLinkResponse':
        """Build from the application DTO."""
        return cls(
            short_code=dto.short_code,
            short_url=dto.short_url,
            original_url=dto.original_url,
            clicks=dto.clicks,
            created_at=dto.created_at,
            last_accessed=dto.last_accessed,
            is_new=dto.is_new,
            from_cache=dto.from_cache,
        )


class ExtendedLinkInfoResponse(BaseModel):
    """Extended link statistics including derived metrics."""

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

    @field_serializer('created_at', 'last_accessed')
    def serialize_dt(self, value: Optional[datetime]) -> Optional[str]:
        if value is None:
            return None
        return value.isoformat()

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "short_code": "abc123",
                "short_url": "https://short.xyz/abc123",
                "original_url": "https://example.com/very/long/url",
                "clicks": 150,
                "created_at": "2026-01-15T10:00:00",
                "last_accessed": "2026-02-20T15:30:00",
                "is_popular": True,
                "is_recent": False,
                "age_days": 36,
                "clicks_per_day": 4.17,
                "last_access_days_ago": 1
            }
        }
    )

    @classmethod
    def from_dto(cls, dto) -> 'ExtendedLinkInfoResponse':
        return cls(
            short_code=dto.short_code,
            short_url=dto.short_url,
            original_url=dto.original_url,
            clicks=dto.clicks,
            created_at=dto.created_at,
            last_accessed=dto.last_accessed,
            is_popular=dto.is_popular,
            is_recent=dto.is_recent,
            age_days=dto.age_days,
            clicks_per_day=dto.clicks_per_day,
            last_access_days_ago=dto.last_access_days_ago
        )

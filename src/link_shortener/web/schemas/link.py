from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_serializer


class ShortLinkResponse(BaseModel):
    """
    Basic link information returned to clients.

    Attributes:
        short_code: The generated short code.
        short_url: Full short URL (base + code).
        original_url: The original long URL.
        clicks: Number of recorded accesses.
        created_at: Timestamp when the link was created.
        last_accessed: Timestamp of the last access (if any).
        is_new: ``True`` if the link was just created.
        from_cache: ``True`` if data came from cache.
    """

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
        """
        Serialize datetime fields to ISO 8601 strings.

        Args:
            value: A timezone-aware datetime or ``None``.

        Returns:
            ISO-formatted string or ``None`` if input is ``None``.
        """
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
    """
    Extended link statistics including derived metrics.

    Attributes:
        short_code: The generated short code.
        short_url: Full short URL.
        original_url: The original long URL.
        clicks: Total click count.
        created_at: Creation timestamp.
        last_accessed: Last access timestamp (if any).
        is_popular: Whether the link's clicks exceed the popular threshold.
        is_recent: Whether the link was created recently (within ``RECENT_DAYS``).
        age_days: Age of the link in whole days.
        clicks_per_day: Average clicks per day since creation.
        last_access_days_ago: Days since the last access (``None`` if never accessed).
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

    @field_serializer('created_at', 'last_accessed')
    def serialize_dt(self, value: Optional[datetime]) -> Optional[str]:
        """
        Serialize datetime fields to ISO 8601 strings.

        Args:
            value: A timezone-aware datetime or ``None``.

        Returns:
            ISO-formatted string or ``None`` if input is ``None``.
        """
        if value is None:
            return None
        return value.isoformat()

    @classmethod
    def from_dto(cls, dto) -> 'ExtendedLinkInfoResponse':
        """
        Build a schema instance from an application DTO.

        Args:
            dto: An ``ExtendedLinkInfoResponse`` DTO from the application layer.

        Returns:
            Populated ``ExtendedLinkInfoResponse`` schema instance.
        """
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

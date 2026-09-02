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
        clicks: Number of recorded accesses; ``None`` when withheld.
        created_at: Timestamp when the link was created.
        last_accessed: Timestamp of the last access (if any).
        expires_at: When the link expires; ``None`` for a permanent one.
        is_new: ``True`` if the link was just created.
        from_cache: ``True`` if data came from cache.
        deletion_token: Returned once, and only to whoever just created a
            link with no account behind it. It is the only way such a link
            can be deleted by the person who made it -- there is no owner
            to compare against, and the address it came from is neither
            stable nor private to one person.
    """

    short_code: str
    short_url: str
    original_url: str
    # Optional because a caller who is not entitled to the link's traffic
    # gets ``None`` rather than a number. Keeping the field and emptying it
    # is deliberate: an absent key would make "withheld" and "this build is
    # older than the field" the same thing on the wire.
    clicks: Optional[int]
    created_at: datetime
    last_accessed: Optional[datetime]
    # Withheld until now, while the dashboard rendered a column from it:
    # every link read "never", including the guest links that had seven
    # days to live.
    expires_at: Optional[datetime] = None
    is_new: bool
    from_cache: bool
    owner_id: Optional[str] = None
    deletion_token: Optional[str] = None

    @field_serializer('created_at', 'last_accessed', 'expires_at')
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
                "expires_at": "2026-02-27T12:00:00",
                "is_new": False,
                "from_cache": True,
                "owner_id": "550e8400-e29b-41d4-a716-446655440000",
                # Published example. B105 reads the key, not the value:
                # the value here is `None`.
                "deletion_token": None  # nosec B105
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
            expires_at=dto.expires_at,
            is_new=dto.is_new,
            from_cache=dto.from_cache,
            owner_id=dto.owner_id,
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
    owner_id: Optional[str] = None

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
                "last_access_days_ago": 1,
                "owner_id": "550e8400-e29b-41d4-a716-446655440000",
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
            last_access_days_ago=dto.last_access_days_ago,
            owner_id=dto.owner_id,
        )

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ShortLinkResponse(BaseModel):
    """Response schema for a short link (created or retrieved)."""

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
        """Serialize datetime fields to ISO format strings."""
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
        """Create a response schema from a ShortLinkResponse DTO."""
        return cls(
            short_code=dto.short_code,
            short_url=dto.short_url,
            original_url=dto.original_url,
            clicks=dto.clicks,
            created_at=dto.created_at,
            last_accessed=dto.last_accessed,
            is_new=dto.is_new,
            from_cache=dto.from_cache
        ) 

class BatchItemResponse(BaseModel):
    """Response schema for a single item in batch creation response."""

    success: bool
    url: str
    short_code: Optional[str] = None
    short_url: Optional[str] = None
    error: Optional[str] = None
    is_new: Optional[bool] = None
    from_cache: Optional[bool] = None
    duplicate_of: Optional[str] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "url": "https://example.com/long",
                "short_code": "abc123",
                "short_url": "https://short.xyz/abc123",
                "is_new": False,
                "from_cache": True,
                "duplicate_of": None
            }
        }
    )

    @classmethod
    def from_dto(cls, dto) -> "BatchItemResponse":
        """Create a response schema from a BatchItemResponse DTO."""
        return cls(
            success=dto.success,
            url=dto.url,
            short_code=dto.short_code,
            short_url=dto.short_url if hasattr(dto, 'short_url') else None,
            error=dto.error,
            is_new=dto.is_new,
            from_cache=dto.from_cache,
            duplicate_of=dto.duplicate_of
        )

class BatchCreateResponse(BaseModel):
    """Response schema for batch creation of short links."""
    
    results: List[BatchItemResponse]
    total: int
    successful: int
    failed: int

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "results": [
                    {
                        "success": True,
                        "url": "https://example.com/1",
                        "short_code": "abc123",
                        "short_url": "https://short.xyz/abc123"
                    },
                    {
                        "success": False,
                        "url": "invalid-url",
                        "error": "Invalid URL"
                    }
                ],
                "total": 2,
                "successful": 1,
                "failed": 1
            }
        }
    )

    @classmethod
    def from_dto(cls, dto) -> "BatchCreateResponse":
        """Create a response schema from a BatchCreateResponse DTO."""
        return cls(
            results=[BatchItemResponse.from_dto(item) for item in dto.items],
            total=dto.total,
            successful=dto.successful,
            failed=dto.failed
        )

class StatsItemResponse(BaseModel):
    """Response schema for a single item in service statistics."""
    
    short_code: str
    short_url: str
    original_url: str
    clicks: int
    created_at: datetime

    @field_serializer('created_at')
    def serialize_dt(self, value: datetime) -> str:
        """Serialize datetime to ISO format string."""
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
        """Create a response schema from a StatsItemResponse DTO."""
        return cls(
            short_code=dto.short_code,
            short_url=dto.short_url,
            original_url=dto.original_url,
            clicks=dto.clicks,
            created_at=dto.created_at
        )

class ServiceStatsResponse(BaseModel):
    """Response schema for service-wide statistics."""
    
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
        """Create a response schema from a ServiceStatsResponse DTO."""
        return cls(
            total_urls=dto.total_urls,
            total_clicks=dto.total_clicks,
            avg_clicks_per_url=dto.avg_clicks_per_url,
            popular_links=[
                StatsItemResponse.from_dto(link)
                for link in dto.popular_links
            ]
        )

class ErrorDetail(BaseModel):
    """Schema for detailed error information (field-level errors)."""

    field: Optional[str] = None
    message: str
    code: Optional[str] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "field": "url",
                "message": "URL must be valid",
                "code": "url_error"
            }
        }
    )

class ErrorResponse(BaseModel):
    """Schema for error responses (both API and frontend)."""
    
    error: str
    message: str
    details: Optional[List[ErrorDetail]] = None
    timestamp: datetime = Field(default_factory=datetime.now)

    @field_serializer('timestamp')
    def serialize_dt(self, value: datetime) -> str:
        """Serialize timestamp to ISO format string."""
        return value.isoformat()

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "error": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "details": [
                    {
                        "field": "url",
                        "message": "URL must be valid",
                        "code": "url_error"
                    }
                ],
                "timestamp": "2026-02-20T12:00:00"
            }
        }
    )

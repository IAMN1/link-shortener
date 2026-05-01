from typing import List, Optional
from pydantic import BaseModel, ConfigDict

class BatchItemResponse(BaseModel):
    """Schema for a single item in a batch response."""

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
        """Build schema from the application DTO."""
        return cls(
            success=dto.success,
            url=dto.url,
            short_code=dto.short_code,
            short_url=dto.short_url,
            error=dto.error,
            is_new=dto.is_new,
            from_cache=dto.from_cache,
            duplicate_of=dto.duplicate_of
        )


class BatchCreateResponse(BaseModel):
    """Aggregated batch response."""

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
        """Build schema from the application DTO."""
        return cls(
            results=[BatchItemResponse.from_dto(item) for item in dto.items],
            total=dto.total,
            successful=dto.successful,
            failed=dto.failed
        )

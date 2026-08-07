from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ErrorDetail(BaseModel):
    """A single validation error detail."""

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
    """Standard API error envelope."""

    error: str
    message: str
    details: Optional[List[ErrorDetail]] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

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
                "timestamp": "2026-02-20T12:00:00+00:00"
            }
        }
    )

    @field_serializer('timestamp')
    def serialize_dt(self, value: datetime) -> str:
        """
        Serialize the timestamp field to an ISO 8601 string.

        Args:
            value: A timezone-aware datetime.

        Returns:
            ISO-formatted string representation.
        """
        return value.isoformat()

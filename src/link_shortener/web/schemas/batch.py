from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, field_serializer

from link_shortener.application.dtos.batch import (
    BatchCreateResponse as ApplicationBatchResponse,
    BatchItemResponse as ApplicationBatchItem,
)
from link_shortener.web.i18n import translate_error

class BatchItemResponse(BaseModel):
    """Schema for a single item in a batch response.

    ``deletion_token`` is present for the same reason it is on the
    single-link response, and was missing here for no reason at all: a guest
    who shortened ten URLs at once could not take back any of them, while a
    guest who shortened one could. The token is filled in by the controller,
    which is where the signing key lives.

    ``retry_after_seconds`` is present on the refusals that clear by
    themselves, and it is here because a ``Retry-After`` header describes a
    whole response. A batch that ran out of the guest's allowance partway
    down the list answers 200 -- some items were created -- and the refused
    ones had nothing to say about when to come back, while the same
    refusal, raised for a batch that got nothing done at all, answers 429
    and sends the header.

    ``error`` is the machine-readable code and ``message`` is the sentence,
    which is what ``ErrorResponse`` means by the same two names. It was the
    other way round here -- ``error`` held the finished sentence and the
    code was dropped -- so one field name meant a reason in one half of the
    API and a translation of it in the other, and the only way to tell a
    malformed URL from a spent quota was to match on text that changes with
    the reader's language. The ``Refusal`` the DTO carries has held the code
    the whole way for exactly this, and the boundary threw it away.
    """

    success: bool
    url: str
    short_code: Optional[str] = None
    short_url: Optional[str] = None
    error: Optional[str] = None
    message: Optional[str] = None
    retry_after_seconds: Optional[int] = None
    is_new: Optional[bool] = None
    from_cache: Optional[bool] = None
    duplicate_of: Optional[str] = None
    expires_at: Optional[datetime] = None
    deletion_token: Optional[str] = None

    @field_serializer('expires_at')
    def serialize_dt(self, value: Optional[datetime]) -> Optional[str]:
        """
        Serialize the expiry to an ISO 8601 string.

        Args:
            value: A timezone-aware datetime or ``None``.

        Returns:
            ISO-formatted string, or ``None`` for a permanent link.
        """
        if value is None:
            return None
        return value.isoformat()

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
    def from_dto(cls, dto: ApplicationBatchItem) -> "BatchItemResponse":
        """Build schema from the application DTO.

        This is where a refused item gets its sentence. The DTO carries the
        refusal with its msgid intact precisely so that the wording happens
        here, in the request whose language is known -- the same place the
        error envelope words a refusal that was raised.

        The code goes out beside it, untranslated, because it is the half a
        caller can act on.
        """
        return cls(
            success=dto.success,
            url=dto.url,
            short_code=dto.short_code,
            short_url=dto.short_url,
            error=dto.error.code if dto.error else None,
            message=translate_error(dto.error) if dto.error else None,
            retry_after_seconds=(
                dto.error.retry_after_seconds if dto.error else None
            ),
            is_new=dto.is_new,
            from_cache=dto.from_cache,
            duplicate_of=dto.duplicate_of,
            expires_at=dto.expires_at,
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
                        "error": "VALIDATION_ERROR",
                        "message": "URL must have a scheme!"
                    }
                ],
                "total": 2,
                "successful": 1,
                "failed": 1
            }
        }
    )

    @classmethod
    def from_dto(cls, dto: ApplicationBatchResponse) -> "BatchCreateResponse":
        """Build schema from the application DTO."""
        return cls(
            results=[BatchItemResponse.from_dto(item) for item in dto.items],
            total=dto.total,
            successful=dto.successful,
            failed=dto.failed
        )

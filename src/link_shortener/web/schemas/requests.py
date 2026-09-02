from typing import List, Optional
from pydantic import ConfigDict, Field

from link_shortener.web.schemas.strict import StrictRequest

from link_shortener.application.dtos.batch import MAX_BATCH_ITEMS


class CreateShortLinkRequest(StrictRequest):
    """Request schema for creating a single short link."""
    url: str = Field(
        ...,
        description="Url to shorten",
        examples=["https://example.com/so-long-url"]
    )
    ttl_seconds: Optional[int] = Field(
        None,
        ge=0,          # 0 means no expiration
        description="Time to live in seconds (0 = forever, None = default behaviour)"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "url": "https://example.com/so-long-url",
                "ttl_seconds": 3600
            }
        }
    )

class BatchCreateLinkRequest(StrictRequest):
    """
    Request schema for batch creation of short links.
    """
    urls: List[str] = Field(
        ...,
        min_length=1,
        max_length=MAX_BATCH_ITEMS,
        description=f"List of URLs to shorten (max {MAX_BATCH_ITEMS})",
        # One example, and it is a list -- `examples` holds values *for
        # this field*, and this field is an array. Written as three bare
        # strings the schema said a valid `urls` is the string
        # "https://example.com/so-long-url-1", which is what a client
        # generated from the document would then send.
        examples=[[
            "https://example.com/so-long-url-1",
            "https://example.com/so-long-url-2",
            "https://example.com/so-long-url-3"
        ]]
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "urls": [
                    "https://example.com/so-long-url-1",
                    "https://example.com/so-long-url-2",
                    "https://example.com/so-long-url-3"
                ]
            }
        }
    )

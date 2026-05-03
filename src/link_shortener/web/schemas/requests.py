from typing import List
from pydantic import BaseModel, ConfigDict, Field


class CreateShortLinkRequest(BaseModel):
    """Request schema for creating a single short link."""
    url: str = Field(
        ...,
        description="Url to shorten",
        examples=["https://example.com/so-long-url"]
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "url": "https://example.com/so-long-url"
            }
        }
    )

class BatchCreateLinkRequest(BaseModel):
    """
    Request schema for batch creation of short links.
    """
    urls: List[str] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="List of URLs to shorten (max 100)",
        examples=[
            "https://example.com/so-long-url-1",
            "https://example.com/so-long-url-2",
            "https://example.com/so-long-url-3"
        ]
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

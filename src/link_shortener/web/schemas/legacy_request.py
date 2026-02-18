from typing import List

from pydantic import BaseModel, Field


class URLCreateRequest(BaseModel):
    """Схема создания короткой ссылки"""
    
    url: str = Field(
        ...,
        description="URL",
        examples=[
            "https://example.com/some/parameters",
            "https://domain.com/aAbBcDE"
        ]
    )


class BatchURLCreateRequest(BaseModel):

    urls: List[str] = Field (
        ...,
        description='Список URLs для сокращения',
        examples=[
            'https://example.com/some/parameters/1',
            'https://example.com/some/parameters/2'
        ],
        min_length=1,
        max_length=100
    )
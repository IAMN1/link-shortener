from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class URLResponse(BaseModel):
    """Схема ответа при создании/получении ссылки"""
    short_code: str = Field(
        ...,
        description='Короткий код ссылки',
        min_length=6,
        max_length=10,
        examples=['aAbBcDE']
    )
    short_url: str = Field(
        description='Полная короткая ссылка',
        examples=['https://domain.com/aAbBcDE']
    )
    original_url: str = Field(
        ...,
        description='Исходный URL',
        examples=["https://example.com/some/parameters"]
    )
    clicks: int = Field(
        default=0,
        description='Количество переходов по ссылке'
    )
    created_at: datetime = Field(
        ...,
        description='Дата создания URL'
    )
    last_accessed: Optional[datetime] = Field(
        None,
        description='Дата последнего обращения к ресурсу'
    )
    already_exists: Optional[bool] = Field(
        ...,
        description='Флаг, указывающий существовала ли ссылка ранее',
    )
    message: Optional[str] = Field(
        ...,
        description='Сообщение о результате операции'
    )

    @field_serializer('created_at', 'last_accessed')
    def serialize_dates(self, value: Optional[datetime], _info) -> str:
        if value is None:
            return None
        return value.isoformat()
    
    model_config = ConfigDict(
        json_schema_extra = {
            "example": {
                "short_code": "aAbBcDE",
                "short_url": "https://domain.com/aAbBcDE",
                "original_url": "https://example.com/some/parameters",
                "clicks": 0,
                "created_at": "2026-01-17T10:30:00",
                "last_accessed": None,
                "already_exists": False,
                "message": "Ссылка успешно создана"
            }
        }
    )


class BatchItemResponse(BaseModel):
    """
    Схема ответа для одного созданного элемента при пакетном создании
    Ответ может быть как успехом, так и ошибкой
    """
    success: bool = Field(
        ...,
        description='Флаг при успешном создании ссылки'
    )
    source_url: str = Field(
        ...,
        description='Исходный URL, который обрабатывался'
    )
    short_code: Optional[str] = Field(
        None,
        description='Короткий код ссылки'
    )
    # Опциональные поля
    short_url: Optional[str] =Field(
        None,
        description='Короткий код (если ссылка обработана успешно)',
        min_length=6,
        max_length=10
    )
    error: Optional[str] = Field(
        None,
        description='Сообщение об ошибке (если в процессе обработки ссылки произошла ошибка)'
    )

    model_config = ConfigDict(
        json_schema_extra = {
            "examples": [
                {
                    "success": True,
                    "source_url": "https://example.com/some/parameters",
                    "short_url": "https://domain.com/aAbBcDE",
                    "short_code": "aAbBcDE"
                },
                {
                    "success": False,
                    "source_url": "https://invalid-url",
                    "error": "Неверный формат URL"
                }
            ]
        }
    )


class BatchURLSResponse(BaseModel):
    """Схема ответа для пакетного создания ссылок"""
    results: List[BatchItemResponse] = Field(
        ...,
        description='Результы обработки каждого URL'
    )
    total: int = Field(
        ...,
        description='Общее количество обработанных URL'
    )
    successful: int = Field(
        ...,
        description='Количество успешно обработанных ссылок'
    )
    failed: int = Field(
        ...,
        description='Количество URL, которые не удалось обработать'
    )

    model_config = ConfigDict(
        json_schema_extra = {
            "example": {
                "results": [
                    {
                        "success": True,
                        "url": "https://example.com/some/parameters",
                        "short_url": "https://domain.com/aAbBcDE",
                        "short_code": "aAbBcDE"
                    },
                    {
                        "success": False,
                        "url": "https://invalid-url",
                        "error": "Неверный формат URL"
                    }
                ],
                "total": 2,
                "successful": 1,
                "failed": 1
            }
        }
    )


class StatsPopularURLItemResponse(BaseModel):
    """Схема ответа для получения статистики по ссылке"""
    short_code: str
    short_url: str
    original_url: str
    clicks: int
    created_at: datetime

    @field_serializer('created_at')
    def serialize_created_at(self, value: datetime, _info) -> str:
        return value.isoformat()

class ServiceStatsResponse(BaseModel):
    """Схема ответа для получения статистики"""
    total_urls: int = Field(
        ...,
        description='Общее количество URLs',
        ge=0
    )
    total_clicks: int = Field(
        ...,
        description='Общее количество переходов по URLs',
        ge=0
    )
    avg_clicks_per_url: float = Field(
        ...,
        description='Среднее количество переходов по URLs',
        ge=0
    )
    popular_urls: List[StatsPopularURLItemResponse] = Field(
        ...,
        description='Топ 10 популярных URLs',
        min_length=1,
        max_length=10
    )

    model_config = ConfigDict(
        json_schema_extra = {
            "example": {
                "total_urls": 10_000,
                "total_clicks": 11_230_034,
                "avg_clicks_per_url": 71.21,
                "popular_urls": [
                    {
                        "short_code": "aAbBcDE",
                        "short_url": "https://domain.com/aAbBcDE",
                        "original_url": "https://example.com/some/parameters1",
                        "clicks": 0,
                        "created_at": "2026-01-17T10:30:00",

                    },
                    {
                        "short_code": "D32AseQ",
                        "short_url": "https://domain.com/D32AseQ",
                        "original_url": "https://example.com/some/parameters",
                        "clicks": 0,
                        "created_at": "2025-12-21T10:30:00",
                    },
                    ...
                ]
            }
        }
    )
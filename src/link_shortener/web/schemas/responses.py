from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ShortLinkResponseSchema(BaseModel):
    """Схема ответа для короткой ссылки"""

    short_code: str = Field(..., description='Короткий код ссылки')
    short_url: str = Field(..., description='Полная короткая ссылка')
    original_url: str = Field(..., description='Оригинальный URL')
    clicks: int = Field(..., description='Количество переходов')
    created_at: datetime = Field(..., description='Дата создания')
    last_accessed: Optional[datetime] = Field(None, description='Дата последнего перехода')
    is_new: bool = Field(False, description='Была ли ссылка создана в этом запросе')
    from_cache: bool = Field(False, description='Были ли данные получены из кэша')

    @field_serializer('created_at', 'last_accessed')
    def serialize_dates(self, value: Optional[datetime], _info) -> str:
        if value is None:
            return None
        return value.isoformat()

    model_config = ConfigDict(
        json_schema_extra={
            'example': {
                'short_code': 'aAbBcDE',
                'short_url': 'https://domain.com/aAbBcDE',
                'original_url': 'https://example.com/some/parameters',
                'clicks': 0,
                'created_at': '2026-01-17T10:30:00',
                'last_accessed': None,
                'is_new' : True,
                'from_cache': False
            }
        }
    )

    @classmethod
    def from_dto(cls, dto) -> 'ShortLinkResponseSchema':
        """создание схемы из DTO"""
        return cls(**dto.dict()) 

class BatchItemResponseSchema(BaseModel):
    """Схема ответа для одного элемента в пакетной обработке"""

    success: bool = Field(..., description='Успешно ли обработан URL')
    url: str = Field(..., description='Оригинальный URL')
    short_code: Optional[str] = Field(None, description='Короткий код (если успешно)')
    short_url: Optional[str] = Field(None, description='Короткая ссылка (если успешно)')
    error: Optional[str] = Field(None, description='Сообщение об ошибке (если есть)')
    is_new: Optional[bool] = Field(None, description='Новая ли ссылка')
    from_cache: Optional[bool] = Field(None, description='Из кэша ли данные')
    duplicate_of: Optional[str] = Field(None, description='URL, дубликатом которого является')

class BatchCreateResponseSchema(BaseModel):
    """Схема ответа для пакетного создания ссылок"""
    
    results: List[BatchItemResponseSchema] = Field(..., description='Результаты обработки')
    total: int = Field(..., description='Общее количество URL')
    successful: int = Field(..., description='Количество успешно обработанных')
    failed: int = Field(..., description='Количество неудачных')


class StatsItemResponseSchema(BaseModel):
    """Схема для элемента статистики"""
    
    short_code: str = Field(..., description='Короткий код')
    short_url: str = Field(..., description='Короткая ссылка')
    original_url: str = Field(..., description='Оригинальный URL (обрезанный)')
    clicks: int = Field(..., description='Количество переходов')
    created_at: datetime = Field(..., description='Дата создания')

    @field_serializer('created_at', 'last_accessed')
    def serialize_dates(self, value: Optional[datetime], _info) -> str:
        if value is None:
            return None
        return value.isoformat()

class ServiceStatsResponseSchema(BaseModel):
    """Схема ответа для статистики сервиса"""
    
    total_urls: int = Field(..., description='Общее количество ссылок')
    total_clicks: int = Field(..., description='Общее количество переходов')
    avg_clicks_per_url: float = Field(..., description='Среднее количество переходов на ссылку')
    popular_links: List[StatsItemResponseSchema] = Field(..., description='Популярные ссылки')


class ErrorDetailSchema(BaseModel):
    """Детали ошибки"""
    
    field: Optional[str] = Field(None, description='Поле, в котором ошибка')
    message: str = Field(..., description='Сообщение об ошибке')
    code: Optional[str] = Field(None, description='Код ошибки')


class ErrorResponseSchema(BaseModel):
    """Схема ответа об ошибке"""
    
    error: str = Field(..., description='Тип ошибки')
    message: str = Field(..., description='Сообщение об ошибке')
    details: Optional[List[ErrorDetailSchema]] = Field(None, description='Детали ошибки')
    timestamp: datetime = Field(default_factory=datetime.now, description='Время ошибки')
    
    model_config = ConfigDict(
        json_schema_extra= {
            'example': {
                'error': "VALIDATION_ERROR",
                'message': 'Ошибка валидации входных данных',
                'details': '...',
                'timestamp': '2026-01-17T10:30:00'
            }
        }
    )
    
    @field_serializer('created_at', 'last_accessed')
    def serialize_dates(self, value: Optional[datetime], _info) -> str:
        if value is None:
            return None
        return value.isoformat()

    @classmethod
    def from_exception(cls, exc: Exception) -> 'ErrorResponseSchema':
        """Создание схемы из исключения"""
        return cls(
            error=exc.__class__.__name__,
            message=str(exc)
        )
    
    @classmethod
    def from_validation_error(cls, exc) -> 'ErrorResponseSchema':
        """Создание схемы из ошибки валидации Pydantic"""
        details = []
        for error in exc.errors():
            details.append(ErrorDetailSchema(
                field=' -> '.join(str(loc) for loc in error['loc']),
                message=error['msg'],
                code=error['type']
            ))
        
        return cls(
            error='VALIDATION_ERROR',
            message='Ошибка валидации входных данных',
            details=details
        )
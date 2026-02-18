from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class ErrorDetail(BaseModel):
    """Детали ошибки для сложных случаев"""
    field: Optional[str] = Field(
        None,
        description='Поле, в котором произошла ошибка'
    )
    message: str = Field(
        ...,
        description='Сообщение'
    )
    code: Optional[str] = Field(
        None,
        description='Код ошибки для конкретного поля'
    )


class ErrorResponse(BaseModel):
    """Схема ответов об ошибке"""
    error: str = Field(
        ...,
        description='Тип ошибки',
        examples=[
            'VALIDATION_ERROR',
            'NOT_FOUND',
            'DATABASE_ERROR'
        ],
    )
    message: str = Field(
        ...,
        description='Сообщение об ошибке',
        examples=['Некоректный URL', 'Ресурс не найден']
    )
    details: Optional[Dict] = Field(
        None,
        description='Детали ошибки'
    )

    model_config = ConfigDict(
        json_schema_extra = {
            "example": {
                "error": "VALIDATION_ERROR",
                "message": "Неверный формат URL",
                "details": {
                    "path": "/api/v1/shorten"
                }
            }
        }
    )

class SuccessResponse(BaseModel):
    """Базовая схема успешного ответа"""
    success: bool = Field(
        True,
        description='Флаг успешного выполнения операции'
    )
    message: str = Field(
        ...,
        description='Сообщение об успешном выполнении'
    )
    
    model_config = ConfigDict(
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Операция выполнена успешно"
            }
        }
    )
from typing import Optional, Dict
from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Схема создания ошрбок"""
    error: str = Field(
        ...,
        description='Тип ошибки',
        examples=['VALIDATION_ERROR'],
    )
    message: str = Field(
        ...,
        description='Сообщение об ошибке',
        examples=['Некоректный URL']
    )
    details: Optional[Dict] = Field(
        None,
        description='Детали ошибки'
    )
from http import HTTPStatus
import logging
import os
from typing import Any, Dict, Optional, Tuple

from flask import request
from pydantic import ValidationError as PydanticValidationError
from link_shortener.exceptions import AppException
from link_shortener.schemas.common_schemas import ErrorResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError


logger = logging.getLogger(__name__)


def register_error_handlers(app):
    """
    Метод для регистрации обработчиков ошибок в flask

    Args:
        app (FLASK): Flask application
    """

    @app.errorhadnler(AppException)
    def handle_app_exception(error: AppException) -> Tuple[Dict[str, Any], int]:
        """Обработка кастомных исключений приложения"""
        logger.warning(
            "AppException: %s (code: %s, status: %d, path: %s)",
            error.message, error.code, error.status_code, request.path
        )
        response = create_error_response(
            error_code=error.code or "UNKNOWN_ERROR",
            message=error.message,
            status_code=error.status_code,
            details={"path": request.path}
        )
        return response
    
    @app.errorhandler(PydanticValidationError)
    def handle_pydantic_validation_error(error: PydanticValidationError) -> Tuple[Dict[str, Any], int]:
        """Обработка ошибок валидации Pydantic"""
        error_details = []
        for err in error.errors():
            error_details.append({
                "field": " -> ".join(str(loc) for loc in err["loc"]),
                "message": err["msg"],
                "type": err["type"]
            })
        
        logger.warning(
            "Pydantic validation error: %s (path: %s)",
            error_details, request.path
        )

        response = create_error_response(
            error_code="VALIDATION_ERROR",
            message="Ошибка валидации входных данных",
            status_code=HTTPStatus.BAD_REQUEST,
            details={
                "errors": error_details,
                "path": request.path
            }
        )
        return response
    

    @app.errorhandler(IntegrityError)
    def handle_integrity_error(error: IntegrityError) -> Tuple[Dict[str, Any], int]:
        """Обработка целостности БД (уникальность и тп.)"""
        logger.error(
            "Database integrity error: %s (path: %s)",
            str(error.orig), request.path, exc_info=True
        )

        # Проверка является ли ошибка нарушением целостности уникальности
        error_msg = str(error.orig)
        if "unique" in error_msg.lower() or "duplicate" in error_msg.lower():
            message = "Нарушение уникальности данных"
        else:
            message = "Нарушение целостности базы данных"

        response = create_error_response(
            error_code="DATABASE_INTEGRITY_ERROR",
            message=message,
            status_code=HTTPStatus.CONFLICT,
            details={
                "path": request.path,
                "original_error": error_msg[:200]
            }
        )
        return response
    
    
    @app.errorhandler(SQLAlchemyError)
    def handle_sqlalchemy_error(error: SQLAlchemyError) -> Tuple[Dict[str, Any], int]:
        """Обработка общих ошибок SQLAlchemy"""
        logger.error(
            "Database error: %s (path: %s)",
            str(error), request.path, exc_info=True
        )
        
        response = create_error_response(
            error_code="DATABASE_ERROR",
            message="Внутрянняя ошибка базы данных",
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            details={
                "path": request.path
            }
        )
        return response
    
    @app.errorhandler(404)
    def handle_not_found(error) -> Tuple[Dict[str, Any], int]:
        """Обработка 404 (Not Found)"""
        response = create_error_response(
            error_code="NOT_FOUND",
            message="Запрошенный ресурс не найден",
            status_code=HTTPStatus.NOT_FOUND,
            details={
                "path": request.path,
                "method": request.method
            }
        )
        return response
    

    @app.errorhandler(405)
    def handle_method_not_allowed(error) -> Tuple[Dict[str, Any], int]:
        """обработка 405 (Method not allowed)"""

        response = create_error_response(
            error_code="METHOD_NOT_ALLOWED",
            message=f"Метод {request.method} не разрешен для данного ресурса",
            status_code=HTTPStatus.METHOD_NOT_ALLOWED,
            details={
                "path": request.path,
                "allowed_methods": error.valid_methods if hasattr(error, 'valid_methods') else []
            }
        )
        return response
    
    @app.errorhandler(429)
    def handle_rate_limit(error) -> Tuple[Dict[str, Any], int]:
        """Обработка 429 (Слишком много запросов)"""

        response = create_error_response(
            error_code="RATE_LIMIT_EXCEEDED",
            message="Превышен лимит запросов. Пожалуйста, попробуйте позже.",
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
            details={
                "path": request.path,
                "retry_after": getattr(error, 'retry_after', None)
            }
        )
        return response
    

    @app.errorhandler(Exception)
    def handle_generic_exception(error: Exception) -> Tuple[Dict[str, Any], int]:
        """
        Обработка всех непредвиденных исключений
        """
        logger.error(
            "Unhandled exception: %s (path: %s)",
            str(error), request.path, exc_info=True
        )
        
        # В production режиме не показываем детали ошибки
        is_production = os.environ.get('FLASK_ENV') == 'PROD'
        

        response = create_error_response(
            error_code="INTERNAL_SERVER_ERROR",
            message="Внутренняя ошибка сервера" if is_production else str(error),
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            details=None if is_production else {
                "path": request.path,
                "exception_type": error.__class__.__name__
            }
        )
        return response


def create_error_response(
    error_code: str,
    message: str,
    status_code: int,
    details: Optional[Dict] = None,
    path: Optional[str] = None
) -> Tuple[Dict[str, Any], int]:
    """
    Утилита для создания стандартизированного ответа об ошибке
    
    Args:
        error_code: Тип ошибки
        message: Сообщение об ошибке
        status_code: HTTP статус код
        details: Дополнительные детали
        path: Путь запроса
    
    Returns:
        Кортеж (response_dict, status_code)
    """
    response = ErrorResponse(
        error=error_code,
        message=message,
        details=details or {"path": path}
    )
    
    return response.model_dump(), status_code

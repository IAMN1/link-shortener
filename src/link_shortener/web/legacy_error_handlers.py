import traceback
from http import HTTPStatus
from typing import Any, Dict, Optional, Tuple

from flask import current_app, request
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from link_shortener.infrastructure.core.logging_config import get_logger
from link_shortener.infrastructure.web.schemas.common import ErrorResponse
from src.link_shortener.web.exceptions import AppException

logger = get_logger(__name__)


def register_error_handlers(app):
    """
    фабричный метод регистрации обработчиков ошибок в flask приложении

    Args:
        app (FLASK): Flask application
    """

    @app.errorhandler(AppException)
    def handle_app_exception(error: AppException) -> Tuple[Dict[str, Any], int]:
        """Обработка кастомных исключений приложения"""

        log_level = 'error' if error.status_code >= 500 else 'warning'

        logger.log(
            log_level,
            "app_exception", 
            exception_type=error.__class__.__name__,
            status_code=error.status_code,
            error_code=error.code, 
            error_message=error.message,
            
            path=request.path,
            method=request.method,
            remote_addr=request.remote_addr,
            traceback=traceback.format_exc() if current_app.debug else None
        )

        response = create_error_response(
            error_code=error.code,
            message=error.message,
            status_code=error.status_code,
            path=request.path
        )
        return response
    
    # ========== PYDANTIC ERRORS ==========
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
            "pydantic_validation_error",
            error_details=error_details,
            path=request.path,
            method=request.method
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

    # ========== SQLALCHEMY ERRORS ==========
    @app.errorhandler(SQLAlchemyError)
    def handle_sqlalchemy_error(error: SQLAlchemyError) -> Tuple[Dict[str, Any], int]:
        """Обработка общих ошибок SQLAlchemy"""
        
        logger.error(
            "database_error",
            error_message=str(error), 
            path=request.path,
            method=request.method,
            exc_info=True
        )
        
        response = create_error_response(
            error_code="DATABASE_ERROR",
            message="Внутрянняя ошибка базы данных",
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            details={
                "path": request.path,
                "original_error": str(error) if current_app.debug else None
            }
        )
        return response

    @app.errorhandler(IntegrityError)
    def handle_integrity_error(error: IntegrityError) -> Tuple[Dict[str, Any], int]:
        """Обработка ошибок целостности БД (уникальность и тп.)"""
        
        error_msg = str(error.orig)

        logger.error(
            "database_integrity_error",
            error_message=error_msg[:200], 
            path=request.path, 
            method=request.method,
            exc_info=True
        )

        # Проверка является ли ошибка нарушением целостности уникальности
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
                "original_error": error_msg[:200] if current_app.debug else None
            }
        )
        return response
    
    # ========== TODO add name ==========
    @app.errorhandler(404)
    def handle_not_found(error) -> Tuple[Dict[str, Any], int]:
        """Обработка 404 (Not Found)"""

        logger.info(
            'not_found',
            method=request.method,
            path=request.path, 
            remote_addr=request.remote_addr
        )

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

        logger.warning(
            'method_not_allowed',
            method=request.method,
            path=request.path, 
            allowed_methods=getattr(error, 'valid_methods', [])
        )

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

        logger.warning(
            'rate_limit_exceeded',
            method=request.method, 
            path=request.path, 
            remote_addr=request.remote_addr
        )

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
            "unhandled_exception",
            error_message=str(error),
            error_type=error.__class__.__name__, 
            
            path=request.path, 
            method=request.method, 
            remote_addr=request.remote_addr,
            exc_info=True
        )
        
        # В production режиме не показываем детали ошибки
        is_production = not current_app.debug
        
        response = create_error_response(
            error_code="INTERNAL_SERVER_ERROR",
            message="Внутренняя ошибка сервера" if is_production else str(error),
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            details= {
                "path": request.path,
                "exception_type": error.__class__.__name__ if not is_production else None
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

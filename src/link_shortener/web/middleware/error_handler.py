import traceback
from datetime import datetime
from typing import Any, Dict, Tuple

from flask import Flask, jsonify, request
from pydantic import ValidationError as PydanticValidationError

from src.link_shortener.application.ports.logger.logger import Logger
from src.link_shortener.domain.exceptions import DomainError
from src.link_shortener.web.schemas.responses import ErrorResponseSchema


class ErrorHandlerMiddleware:
    """
    Middleware для обработки ошибок.
    """
    
    def __init__(self, app: Flask, logger: Logger):
        self.app = app
        self.logger = logger
        self._register_error_handlers()
    
    def _register_error_handlers(self):
        """Регистрация обработчиков ошибок"""
        
        @self.app.errorhandler(PydanticValidationError)
        def handle_pydantic_error(error: PydanticValidationError):
            return self._handle_validation_error(error)
        
        @self.app.errorhandler(DomainError)
        def handle_domain_error(error: DomainError):
            return self._handle_domain_error(error)
        
        @self.app.errorhandler(ValueError)
        def handle_value_error(error: ValueError):
            return self._handle_value_error(error)
        
        @self.app.errorhandler(Exception)
        def handle_generic_error(error: Exception):
            return self._handle_generic_error(error)
    

    def _handle_validation_error(self, error: PydanticValidationError) -> Tuple[Dict[str, Any], int]:
        """Обработка ошибок валидации Pydantic"""
        error_response = ErrorResponseSchema.from_validation_error(error)
        
        self.logger.warning(
            "Validation error",
            error_type="VALIDATION_ERROR",
            path=request.path,
            method=request.method,
            details=error_response.details
        )
        
        return jsonify(error_response.model_dump()), 400
    
    def _handle_domain_error(self, error: DomainError) -> Tuple[Dict[str, Any], int]:
        """Обработка доменных ошибок"""
        error_response = ErrorResponseSchema.from_exception(error)
        
        log_context = {
            'error_type': error.code,
            'path': request.path,
            'method': request.method,
            'error_message': error.message
        }
        
        if error.code == "LINK_NOT_FOUND":
            self.logger.warning("Link not found", **log_context)
            status_code = 404
        elif error.code == "VALIDATION_ERROR":
            self.logger.warning("Domain validation error", **log_context)
            status_code = 400
        else:
            self.logger.error("Domain error", **log_context)
            status_code = 400
        
        return jsonify(error_response.model_dump()), status_code
    
    def _handle_value_error(self, error: ValueError) -> Tuple[Dict[str, Any], int]:
        """Обработка ошибок значений"""
        error_response = ErrorResponseSchema.from_exception(error)
        
        self.logger.warning(
            "Value error",
            error_type="VALUE_ERROR",
            path=request.path,
            method=request.method,
            error_message=str(error)
        )
        
        return jsonify(error_response.model_dump()), 400
    
    def _handle_generic_error(self, error: Exception) -> Tuple[Dict[str, Any], int]:
        """Обработка общих ошибок"""
        error_response = ErrorResponseSchema(
            error="INTERNAL_ERROR",
            message="Internal server error",
            timestamp=datetime.now()
        )
        
        # Логируем с traceback
        self.logger.error(
            "Internal server error",
            error_type=error.__class__.__name__,
            path=request.path,
            method=request.method,
            error_message=str(error),
            traceback=traceback.format_exc()
        )
        
        return jsonify(error_response.model_dump()), 500
import time
from typing import Any, Dict, Optional
from flask import Flask, Response, g, request
from link_shortener.infrastructure.core.logging_config import get_logger

logger = get_logger(__name__)

class RequestLoggingMiddleware:
    """
    Middleware для логирование HTTP запросов
    Производит логирование:
    - Начало обработки запроса
    - Завершение обработки запроса
    - HTTP статус код ответа
    - Основную информацию о запросе (method, path, IP...)
    """

    def __init__(self, app: Flask):
        self.app = app
        self._register_handlers()

        logger.info('middleware_initialized', middleware_name=self.__class__.__name__)
    
    def _register_handlers(self):
        """Регистрация обработчиков before_request & after_request"""

        @self.app.before_request
        def before_request():
            """Логирование начала обработки запроса"""
            g.request_start_time = time.time()

            # получение логгера с контекстом запроса
            request_context = self._get_request_context()

            # логирование начала обработки
            logger.debug("request_started" **request_context)

        @self.app.after_request
        def after_request(response: Response) -> Response:
            """Логирование Завершения обработки запроса"""

            # Вычисление времени обработки запроса
            processing_time = 0
            if hasattr(g, 'request_start_time'):
                processing_time = time.time() - g.request_start_time
            
            response_context = self._get_response_context(response, processing_time)

            # Уровень логирования в зависимости от статуса ответа
            if response.status_code >= 500:
                logger.error("request_completed", **response_context)
            elif response.status_code >= 400:
                logger.warning("request_completed", **response_context)
            else:
                logger.info("request_completed", **response_context)
            
            return response
        
        @self.app.teardown_request
        def teardown_request(exception: Optional[Exception] = None):
            """Очистка контекста запроса"""
            if hasattr(g, 'request_start_time'):
                del g.request_start_time
            
            if exception:
                logger.error('request_teardown_error', error=str(exception), path=request.path, method=request.method)

    def _get_request_context(self) -> Dict[str, Any]:
        """Сбор контекста запроса для логирования"""
        return {
            'method': request.method,
            'path': request.path,
            'remote_addr': request.remote_addr,
            'user_agent': request.user_agent.string[:200] if request.user_agent else None,
            'content_type': request.content_type,
            'content_length': request.content_length or 0,
            'query_string': request.query_string.decode() if request.query_string else None,
        }
    
    def _get_response_context(self, response: Response, processing_time: float) -> Dict[str, Any]:
        """Сбор контекста ответа для логирования"""
        return {
            'method': request.method,
            'path': request.path,
            'status_code': response.status_code,
            'processing_time_ms': round(processing_time * 1000, 2),
            'remote_addr': request.remote_addr,
            'response_size': response.content_length or 0,
            'response_content_type': response.content_type,
        }
        
def init_middleware_request_logging(app: Flask) -> RequestLoggingMiddleware:
    """
    Инициализация middleware для логирования запросов

    Args:
        app (Flask): Flask application

    Returns:
        RequestLoggingMiddleware: экземпляр middleware
    """

    logger.debug(
        'initializing_request_logging_middleware',
        app_name=app.name
    )
    return RequestLoggingMiddleware(app)

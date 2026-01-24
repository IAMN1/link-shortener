"""Middleware логирования HTTP запросов"""

import time
from flask import Flask, g, request
import structlog
from link_shortener.core.logging_config import get_logger


logger = get_logger(__name__)

class RequestLoggingMiddleware:
    """
    Производит логирование:
    - Начало обработки запроса
    - Завершение обработки запроса
    - HTTP статус код ответа
    - Информацию о запросе (method, path, IP...)
    """

    def __init__(self, app: Flask):
        self.app = app
        self._register_handlers()

        logger.info(
            'request_logging_middleware_initialized',
            middleware_name=self.__class__.__name__
        )
    
    def _register_handlers(self):
        """Регистрация обработчиков before_request & after_request"""

        @self.before_request
        def before_request_logging():
            """Логирование информации о входящем запросе"""
            g.start_time = time.time()

            # получение логгера с контекстом запроса
            request_logger = structlog.get_logger("request")
            request_logger = request_logger.bind(
                method=request.method,
                path=request.path,
                remote_addr=request.remote_addr,
                user_agent=request.user_agent.string if request.user_agent else None
            )

            # логирование начала обработки
            request_logger.debug("request_started")

        @self.after_request
        def after_request_logging(response):
            """Логирование информации об ответе"""

            # Вычисление времени обработки запроса
            if hasattr(g, 'start_time'):
                processing_time = time.time() - g.start_time
            else:
                processing_time = 0
            

            request_logger = structlog.get_logger("request")
            request_logger = request_logger.bind(
                method=request.method,
                path=request.path,
                status_code=response.status_code,
                processing_time=f"{processing_time:.3f}",
                remote_addr=request.remote_addr,
                content_length=response.content_length,
                content_type=response.content_type,
            )

            # Уровень логирования в зависимости от статуса ответа
            if response.status_code >= 500:
                request_logger.error("request_completed")
            elif response.status_code >= 400:
                request_logger.warning("request_completed")
            else:
                request_logger.info("request_completed")
            
            return response

def init_middleware_request_logging(app: Flask) -> RequestLoggingMiddleware:
    """
    Инициализация middleware для логирования запросов

    Args:
        app (Flask): Flask application

    Returns:
        RequestLoggingMiddleware: экземпляр middleware
    """

    logger.info(
        'initializing_request_logging_middleware',
        app_name=app.name
    )

    return RequestLoggingMiddleware(app)

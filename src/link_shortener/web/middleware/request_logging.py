import time
from typing import Any, Dict

from flask import Flask, Response, g, request

from src.link_shortener.application.ports.logger.logger import Logger


class RequestLoggingMiddleware:
    """
    Middleware для логирования HTTP запросов.
    """
    
    def __init__(self, app: Flask, logger: Logger):
        self.app = app
        self.logger = logger
        self._register_handlers()

        logger.info('middleware_initialized', middleware_name=self.__class__.__name__)
    
    def _generate_request_id(self) -> str:
        """Генарция уникального id запроса"""
        import uuid
        return str(uuid.uuid4)[:10]

    def _register_handlers(self):
        """Регистрация обработчиков Flask"""
        
        @self.app.before_request
        def before_request():
            """Логирование начала обработки запроса"""

            g.request_start_time = time.time()
            g.request_id = self._generate_request_id()
            
            context = self._get_request_context()
            self.logger.info('Request started', **context)
        
        @self.app.after_request
        def after_request(response: Response) -> Response:
            """Логирование Завершения обработки запроса"""

            if hasattr(g, 'request_start_time'):
                processing_time = time.time() - g.request_start_time
                
                context = self._get_response_context(response, processing_time)
                
                # Логируем в зависимости от статуса
                if response.status_code >= 500:
                    self.logger.error('Request completed', **context)
                elif response.status_code >= 400:
                    self.logger.warning('Request completed', **context)
                else:
                    self.logger.info('Request completed', **context)
            
            return response
        
        @self.app.teardown_request
        def teardown_request(exception: Exception = None):
            """Очистка контекста запроса"""
            if exception:
                context = {
                    'path': request.path,
                    'method': request.method,
                    'exception': str(exception)
                }
                self.logger.error('Request teardown with exception', **context)
    

    def _get_request_context(self) -> Dict[str, Any]:
        """Сбор контекста запроса"""
        context = {
            'request_id': g.get('request_id'),
            'method': request.method,
            'path': request.path,
            'remote_addr': request.remote_addr,
            'user_agent': request.user_agent.string[:200] if request.user_agent else None,
        }
        
        # Добавление query parameters (если есть)
        if request.args:
            context['query_params'] = dict(request.args)
        
        # Добавление заголовков (без чувствительных данных)
        safe_headers = {
            'content_type': request.content_type,
            'content_length': request.content_length,
            'accept': request.headers.get('Accept'),
            'accept_encoding': request.headers.get('Accept-Encoding'),
        }
        context.update(safe_headers)
        
        return context
    
    def _get_response_context(self, response: Response, processing_time: float) -> Dict[str, Any]:
        """Сбор контекста ответа"""
        context = {
            'request_id': g.get('request_id'),
            'method': request.method,
            'path': request.path,
            'status_code': response.status_code,
            'processing_time_ms': round(processing_time * 1000, 2),
            'response_size': response.content_length,
            'response_content_type': response.content_type,
        }
        
        # Добавление информации о скорости
        if processing_time > 0:
            context['requests_per_second'] = round(1 / processing_time, 2)
        
        return context
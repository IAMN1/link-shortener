from datetime import datetime
import logging
import logging.handlers
import os
from typing import Any, Dict, Optional
from flask import Flask
import time

from link_shortener.core.config import BaseConfig


class LoggingConfig:
    """
    Класс для хранения и управления конфигурациями логирования.
    Для подтягивания необходимых данных из конфига flask (DRY)
    """

    def __init__(self, flask_cfg: Dict[str, Any]):
        self.log_dir: str = flask_cfg.get('LOG_DIR', BaseConfig.LOG_DIR)
        self.log_file_name: str = flask_cfg.get('LOG_FILENAME', BaseConfig.LOG_FILENAME)
        self.log_format: str = flask_cfg.get('LOG_FORMAT', BaseConfig.LOG_FORMAT)
        self.log_date_format: str = flask_cfg.get('LOG_DATE_FORMAT', BaseConfig.LOG_DATE_FORMAT)
        self.log_max_bytes: int = flask_cfg.get('LOG_MAX_BYTES', BaseConfig.LOG_MAX_BYTES)
        self.log_backup_files_count: int = flask_cfg.get('LOG_BACKUP_FILES_COUNT', BaseConfig.LOG_BACKUP_FILES_COUNT)
        self.log_to_console: bool = flask_cfg.get('LOG_TO_CONSOLE', BaseConfig.LOG_TO_CONSOLE)
        self.log_to_file: bool = flask_cfg.get('LOG_TO_FILE', BaseConfig.LOG_TO_FILE)
        self.debug: bool = flask_cfg.get('DEBUG', BaseConfig.DEBUG)
        self.log_level = flask_cfg.get('LOG_LEVEL', logging.INFO)
        self.request_log_level = flask_cfg.get('REQUEST_LOG_LEVEL', BaseConfig.REQUEST_LOG_LEVEL)

    @property
    def should_log_to_file(self) -> bool:
        """Свойство проверяющее необходимость логирования в файл"""
        return self.log_to_file and bool(self.log_dir)
    
    def get_log_file_path(self) -> Optional[str]:
        """
        Возвращает полный путь к файлу лога
        Собирает все части пути в одном файле

        Returns:
            Optional[str]: Полный путь к файлу лога
        """
        if not self.should_log_to_file:
            return None
        
        # Дополняем имя датой
        date_str = datetime.now().strftime('%Y-%m-%d')
        filename = f'{self.log_file_name}_{date_str}.log'

        return os.path.join(self.log_dir, filename)
    
    def get_formatter(self) -> logging.Formatter:
        return logging.Formatter(
            fmt=self.log_format,
            datefmt=self.log_date_format
        )


def setup_logging(app: Flask) -> None:
    """
    Настройка логирования для Flask app

    Args:
        app (Flask): Flask application
    """

    log_config = LoggingConfig(app.config)

    # create catalog for loggs if not exist
    if log_config.should_log_to_file:
        os.makedirs(log_config.log_dir, exist_ok=True)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(log_config.log_level)
    
    # отчищаем существующие обработчики (чтобы не дублировать логи)
    root_logger.handlers.clear()

    formatter = log_config.get_formatter()

    # CONSOLE HANDLER
    if log_config.log_to_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_config.log_level)
        console_handler.setFormatter(formatter)
        
        root_logger.addHandler(console_handler)

    # FILE HANDLER
    if log_config.should_log_to_file:
        file_path = log_config.get_log_file_path()
        if file_path:
            # RotatingHandler для ротации логов
            # Когда файл достигнет максимального размера, создается новый
            file_handler = logging.handlers.RotatingFileHandler(
                filename=file_path,
                maxBytes=log_config.log_max_bytes,
                backupCount=log_config.log_backup_files_count,
                encoding='utf-8'
            )
            file_handler.setLevel(log_config.log_level)
            file_handler.setFormatter(formatter)
            
            root_logger.addHandler(file_handler)

    
    # LOGGERS FOR THIRD-PARTY LIBS

    # SQLAlchemy
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)

    # Flask/Werkzeug
    werkzeug_level = logging.INFO if log_config.debug else logging.WARNING
    logging.getLogger('werkzeug').setLevel(werkzeug_level)

    # LOGGER FOR HTTP-REQUESTS (ACCESS LOGS)
    setup_request_logging(app)
    

    # Логирование успешной настройки приложения
    app.logger.info(f'Инициализировано логирование с уровнем: {log_config.log_level}')
    app.logger.info(f'Логи в файл: {log_config.log_to_file}')
    if log_config.log_to_file:
        app.logger.info(f'Дирректория логов: {log_config.log_dir}')

def setup_request_logging(app: Flask) -> None:
    """
    Настраивает логирование HTTP запросов

    Args:
        app (Flask): Flask application
    """
    from flask import request, g

    request_logger = logging.getLogger('request')

    # Add Middleware for logging requests
    @app.before_request
    def before_request_logging():
        """Логирование информации о входящем запросе"""
        
        g.start_time = time.time()

        app.logger.debug(
            f'Начало обработки запроса: {request.method} {request.path} '
            f'от {request.remote_addr}'
        )
    
    @app.after_request
    def after_request_logging(response):
        """Логирование информации об ответе"""

        # Вычисление времени обработки
        if hasattr(g, 'start_time'):
            processing_time = time.time() - g.start_time
        else:
            processing_time = 0
        
        # Уровень логирования в зависимости от статуса ответа
        if response.status_code >= 500:
            log_level = logging.ERROR
        elif response.status_code >= 400:
            log_level = logging.WARNING
        else:
            log_level = app.config.get('REQUEST_LOG_LEVEL', logging.INFO)
        
        log_message = (
            f'Completed: {request.method} {request.path} -> '
            f'{response.status_code} '
            f'[{processing_time:.3f} sec] '
            f'from {request.remote_addr}'
        )

        request_logger.log(log_level, log_message)

        return response


def get_logger(name: str) -> logging.Logger:
    """
    Создает и возвращает логгер с заданным именем
    для единого управления логерами и их настройкой

    Args:
        name (str): Имя логгера (default: __name__ of module)

    Returns:
        logging.Logger: logger with setup parameters
    """
    return logging.getLogger(name)


# Добавил на будущее, 
# возможно использую контекстынй менеджер 
# в одном из модулей отвечающих за бизнес логику
# пока только изучаю возможности контекстных менеджеров
class LogContext:
    """Контекстный менеджер для логирования с дополнительным контекстом"""

    def __init__(self, logger: logging.Logger, message: str, **context):
        self.logger = logger
        self.message = message
        self.context = context
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        context_str = ' '.join(f'{k}={v}' for k, v in self.context.items())
        self.logger.debug(f'Start: {self.message} [{context_str}] ')
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        
        processing_time = time.time() - self.start_time
        
        if exc_type is None:
            context_str = ' '.join(f'{k}={v}' for k,v in self.context.items())
            self.logger.debug(
                f'Success: {self.message} [{context_str}] '
                f'for {processing_time:.3f} sec'
            )
        else:
            self.logger.error(
                f'Error: {self.message} - {exc_type.__name__}: {exc_val}',
                exc_info=True
            )






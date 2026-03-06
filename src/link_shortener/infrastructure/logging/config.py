import logging
import logging.handlers
import os
from datetime import datetime
from typing import Any, Dict, Optional

import flask
import structlog
from flask import Flask, has_request_context


class StructLogConfig:
    """
    Configuration holder for structlog settings.

    Extracts logging-related configuration from Flask app config
    and provides convenient access to log file paths and settings.
    """

    def __init__(self, flask_cfg: Dict[str, Any]):
        """
        Initialize from Flask config dictionary.

        Args:
            flask_cfg: Flask app.config dictionary.
        """

        from link_shortener.infrastructure.config.base import BaseConfig

        self.log_dir: str = flask_cfg.get("LOG_DIR", BaseConfig.LOG_DIR)
        self.log_file_name: str = flask_cfg.get("LOG_FILENAME", BaseConfig.LOG_FILENAME)
        self.log_date_format: str = flask_cfg.get(
            "LOG_DATE_FORMAT", BaseConfig.LOG_DATE_FORMAT
        )
        self.log_max_bytes: int = flask_cfg.get(
            "LOG_MAX_BYTES", BaseConfig.LOG_MAX_BYTES
        )
        self.log_backup_files_count: int = flask_cfg.get(
            "LOG_BACKUP_FILES_COUNT", BaseConfig.LOG_BACKUP_FILES_COUNT
        )
        self.log_to_console: bool = flask_cfg.get(
            "LOG_TO_CONSOLE", BaseConfig.LOG_TO_CONSOLE
        )
        self.log_to_file: bool = flask_cfg.get("LOG_TO_FILE", BaseConfig.LOG_TO_FILE)
        self.debug: bool = flask_cfg.get("DEBUG", BaseConfig.DEBUG)
        self.log_level = logging.DEBUG if self.debug else logging.INFO

    @property
    def should_log_to_file(self) -> bool:
        """Check if file logging is enabled and log directory is set."""
        return self.log_to_file and bool(self.log_dir)

    def get_log_file_path(self) -> Optional[str]:
        """
        Construct full path to the log file with date in filename.

        Returns:
            Full path string or None if file logging is disabled.
        """

        if not self.should_log_to_file:
            return None

        # Дополняем имя датой
        date_str = datetime.now().strftime("%Y-%m-%d")
        filename = f"{self.log_file_name}_{date_str}.log"

        return os.path.join(self.log_dir, filename)


def _add_request_context(logger, method_name, event_dict):
    """
    Structlog processor that adds Flask request context to log entries.

    If the code is running within a request context, adds:
        - request_id (if set in g)
        - request_path
        - request_method
        - remote_addr
    """

    if has_request_context():
        event_dict["request_id"] = getattr(flask.g, "request_id", None)
        event_dict["request_path"] = flask.request.path
        event_dict["request_method"] = flask.request.method
        event_dict["remote_addr"] = flask.request.remote_addr
    return event_dict


def _setup_structlog(config: StructLogConfig):
    """
    Configure structlog with processors and renderer based on environment.

    Args:
        config: StructLogConfig instance.
    """

    processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt=config.log_date_format),
        _add_request_context,
        structlog.processors.StackInfoRenderer(),

    ]
    if config.debug:
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    processors.append(renderer)

    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def setup_logging(app: Flask) -> None:
    """
    Set up structlog logging for the Flask application.

    Configures structlog, adds console and/or rotating file handlers,
    and sets log levels for third-party libraries.

    Args:
        app: Flask application instance.
    """

    log_config = StructLogConfig(app.config)

    # create catalog for loggs if not exist
    if log_config.should_log_to_file:
        os.makedirs(log_config.log_dir, exist_ok=True)

    # Configure root logger as a transport for structlog
    root_logger = logging.getLogger()
    root_logger.setLevel(log_config.log_level)
    # Remove default handlers
    root_logger.handlers.clear()

    # Configure structlog
    _setup_structlog(log_config)

    # Console handler
    if log_config.log_to_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_config.log_level)
        console_handler.setFormatter(logging.Formatter("%(message)s"))

        root_logger.addHandler(console_handler)

    # File handler (rotating)
    if log_config.should_log_to_file:
        file_path = log_config.get_log_file_path()
        if file_path:
            # RotatingHandler для ротации логов
            # Когда файл достигнет максимального размера, создается новый
            file_handler = logging.handlers.RotatingFileHandler(
                filename=file_path,
                maxBytes=log_config.log_max_bytes,
                backupCount=log_config.log_backup_files_count,
                encoding="utf-8",
            )
            file_handler.setLevel(log_config.log_level)
            file_handler.setFormatter(logging.Formatter("%(message)s"))

            root_logger.addHandler(file_handler)

    # Set log levels for third-party libraries

    # SQLAlchemy
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    # Werkzeug
    werkzeug_level = logging.INFO if log_config.debug else logging.WARNING
    logging.getLogger("werkzeug").setLevel(werkzeug_level)


    # Log successful initialization
    logger = structlog.get_logger(__name__)
    logger.info(
        "structlog_initialized",
        log_level=log_config.log_level,
        debug_mode=log_config.debug,
        log_to_console=log_config.log_to_console,
        log_to_file=log_config.log_to_file,
        log_dir=log_config.log_dir if log_config.log_to_file else None,
    )


def get_logger(name: str = None) -> structlog.BoundLogger:
    """
    Get a structlog logger with the given name.

    This function centralizes logger creation, ensuring consistent configuration.

    Args:
        name: Logger name (usually __name__).

    Returns:
        Structlog BoundLogger.
    """
    return structlog.get_logger(name)

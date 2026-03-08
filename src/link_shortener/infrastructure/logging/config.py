import logging
import logging.handlers
import os

from link_shortener.infrastructure.logging.settings import LoggingSettings
import structlog
from flask import has_request_context, g, request


def _add_request_context(logger, method_name, event_dict):
    """
    Add Flask request context to log entries if available.
    """

    if has_request_context():
        event_dict["request_id"] = getattr(g, "request_id", None)
        event_dict["request_path"] = request.path
        event_dict["request_method"] = request.method
        event_dict["remote_addr"] = request.remote_addr
    return event_dict


def _configure_structlog(settings: LoggingSettings):
    """
    Set up structlog with processors and renderer based on settings.
    """

    processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt=settings.log_date_format, utc=True),
        _add_request_context,
        structlog.processors.StackInfoRenderer(),

    ]
    if settings.debug:
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


def _setup_console_handler(settings: LoggingSettings, root_logger: logging.Logger):
    """
    Add console handler if enabled.
    """
    if settings.log_to_console:
        handler = logging.StreamHandler()
        handler.setLevel(settings.log_level)
        handler.setFormatter(logging.Formatter("%(message)s"))

        root_logger.addHandler(handler)


def _setup_file_handler(settings: LoggingSettings, root_logger: logging.Logger):
    """
    Add file handler (WatchedFileHandler) if enabled.
    (WatchedFileHandler, rotation externally by logrotate)
    """
    if settings.should_log_to_file:
        os.makedirs(settings.log_dir, exist_ok=True)
        handler = logging.handlers.WatchedFileHandler(
            filename=settings.log_file_path,
            encoding="utf-8",
        )
        handler.setLevel(settings.log_level)
        handler.setFormatter(logging.Formatter("%(message)s"))

        root_logger.addHandler(handler)



def setup_logging(settings: LoggingSettings) -> None:
    """
    Main entry point for logging configuration.
    Must be called once during application initialization.

    Args:
        settings: LoggingSettings object containing all configuration parameters.
    """

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(settings.log_level)
    root_logger.handlers.clear()

    # Configure structlog
    _configure_structlog(settings)

    # Add handlers
    _setup_console_handler(settings, root_logger)
    _setup_file_handler(settings, root_logger)


    # Set log levels for third-party libraries

    # SQLAlchemy
    sqlalchemy_level = getattr(logging, settings.sqlalchemy_log_level.upper(), logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(sqlalchemy_level)

    # Werkzeug
    werkzeug_level = getattr(logging, settings.werkzeug_log_level.upper(), logging.WARNING)
    logging.getLogger("werkzeug").setLevel(werkzeug_level)


    # Log successful initialization
    logger = structlog.get_logger(setup_logging.__module__)
    logger.info(
        "logging_initialized",
        debug_mode=settings.debug,
        log_level=settings.log_level,
        log_to_console=settings.log_to_console,
        log_to_file=settings.log_to_file,
        log_dir=settings.log_dir if settings.log_to_file else None,
        log_file=settings.log_file_path if settings.log_to_file else None,
        sqlalchemy_log_level=sqlalchemy_level,
        werkzeug_log_level=werkzeug_level
    )

import logging
import logging.handlers
import os

import flask
from link_shortener.infrastructure.logging.settings import LoggingSettings
import structlog
from flask import Flask, has_request_context


def _add_request_context(logger, method_name, event_dict):
    """
    Add Flask request context to log entries if available.
    """

    if has_request_context():
        event_dict["request_id"] = getattr(flask.g, "request_id", None)
        event_dict["request_path"] = flask.request.path
        event_dict["request_method"] = flask.request.method
        event_dict["remote_addr"] = flask.request.remote_addr
    return event_dict


def _configure_structlog(config: LoggingSettings):
    """
    Set up structlog with processors and renderer.
    """

    processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt=config.log_date_format, utc=True),
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



def setup_logging(app: Flask) -> None:
    """
    Main entry point for logging configuration.
    Must be called once during application initialization.
    """

    settings = LoggingSettings(app.config)

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
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    # Werkzeug
    werkzeug_level = logging.INFO if settings.debug else logging.WARNING
    logging.getLogger("werkzeug").setLevel(werkzeug_level)


    # Log successful initialization
    logger = structlog.get_logger(__name__)
    logger.info(
        "logging_initialized",
        log_level=settings.log_level,
        debug_mode=settings.debug,
        log_to_console=settings.log_to_console,
        log_to_file=settings.log_to_file,
        log_dir=settings.log_dir if settings.log_to_file else None,
        log_file=settings.log_file_path if settings.log_to_file else None
    )

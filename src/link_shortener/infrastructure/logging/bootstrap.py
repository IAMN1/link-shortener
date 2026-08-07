import logging
import logging.handlers
import os
import structlog

from link_shortener.infrastructure.logging.structlog_config import configure_structlog
from link_shortener.infrastructure.logging.logging_settings import LoggingSettings
from link_shortener.infrastructure.logging.formatters.console_formatter import ConsoleFormatter
from link_shortener.infrastructure.logging.formatters.json_formatter import JSONFormatter


def _setup_console_handler(settings: LoggingSettings, root_logger: logging.Logger):
    """
    Add a console handler to the root logger.

    For the 'standard' logger type, a plain text ConsoleFormatter is used.
    For other types (structlog), a structlog ProcessorFormatter with ConsoleRenderer is used,
    which produces coloured output when debug is enabled.

    Args:
        settings: LoggingSettings object.
        root_logger: Root logger instance.
    """
    if not settings.log_to_console:
        return
    
    if settings.logger_type == "standard":
        handler = logging.StreamHandler()
        handler.setLevel(settings.get_log_level_int())
        formatter = ConsoleFormatter()
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)
        formatter = structlog.stdlib.ProcessorFormatter(processor=renderer)
        handler = logging.StreamHandler()
        handler.setLevel(settings.get_log_level_int())
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)


def _setup_file_handler(settings: LoggingSettings, root_logger: logging.Logger):
    """
    Add a file handler for general application logs.

    For 'standard' logger type, a JSONFormatter is used.
    For other types, a structlog ProcessorFormatter with JSONRenderer is used.
    The log file is watched for external rotation (WatchedFileHandler).

    Args:
        settings: LoggingSettings object.
        root_logger: Root logger instance.
    """
    if not settings.should_log_to_file:
        return
    
    os.makedirs(settings.log_dir, exist_ok=True)
    
    if settings.logger_type == "standard":
        formatter = JSONFormatter(date_format=settings.log_date_format)
    else:
        renderer = structlog.processors.JSONRenderer()
        formatter = structlog.stdlib.ProcessorFormatter(processor=renderer)

    handler = logging.handlers.WatchedFileHandler(
        filename=settings.log_file_path,
        encoding="utf-8",
    )
    handler.setLevel(settings.get_log_level_int())
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

def _setup_audit_handler(settings: LoggingSettings):
    """
    Configure a dedicated logger for audit events.

    Audit logs are written to a separate file (audit.log) and optionally to the console.
    The same formatting logic (plain text or structlog) is applied based on logger_type.

    Args:
        settings: LoggingSettings object.
    """

    if not settings.audit_enabled:
        return
    
    audit_logger = logging.getLogger("audit")
    audit_logger.handlers.clear()
    audit_logger.propagate = False
    audit_logger.setLevel(logging.INFO)
    
    # Console handler
    if settings.log_to_console:
        if settings.logger_type == "standard":
            handler = logging.StreamHandler()
            handler.setLevel(logging.INFO)
            formatter = ConsoleFormatter()
            handler.setFormatter(formatter)
            audit_logger.addHandler(handler)
        else:
            renderer = structlog.dev.ConsoleRenderer(colors=True)
            formatter = structlog.stdlib.ProcessorFormatter(processor=renderer)
            handler = logging.StreamHandler()
            handler.setLevel(logging.INFO)
            handler.setFormatter(formatter)
            audit_logger.addHandler(handler)

    # File handler
    if settings.should_log_to_file:
        os.makedirs(settings.log_dir, exist_ok=True)
        
        if settings.logger_type == "standard":
            formatter = JSONFormatter(date_format=settings.log_date_format)
        else:
            renderer = structlog.processors.JSONRenderer()
            formatter = structlog.stdlib.ProcessorFormatter(processor=renderer)

        audit_file = os.path.join(settings.log_dir, f"{settings.audit_log_filename}.log")
        
        handler = logging.handlers.WatchedFileHandler(audit_file, encoding="utf-8")
        handler.setLevel(logging.INFO)
        handler.setFormatter(formatter)
        audit_logger.addHandler(handler)

def _setup_error_handler(settings: LoggingSettings, root_logger: logging.Logger):
    """
    Add a file handler that captures only ERROR and above messages.

    Error logs are written to a separate file (error.log) in the same format
    as general application logs (JSON or structured text).

    Args:
        settings: LoggingSettings object.
        root_logger: Root logger instance.
    """
    if not settings.log_to_file:
        return
    
    os.makedirs(settings.log_dir, exist_ok=True)
    
    if settings.logger_type == "standard":
        formatter = JSONFormatter(date_format=settings.log_date_format)
    else:
        renderer = structlog.processors.JSONRenderer()
        formatter = structlog.stdlib.ProcessorFormatter(processor=renderer)
    
    error_file = os.path.join(settings.log_dir, f"{settings.error_log_filename}.log")
    
    handler = logging.handlers.WatchedFileHandler(error_file, encoding="utf-8")
    handler.setLevel(logging.ERROR)
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

def setup_logging(settings: LoggingSettings, logging_enabled: bool, audit_enabled: bool) -> None:
    """
    Main entry point for logging configuration.

    Configures structlog, sets up handlers on the root logger, and configures
    the audit logger. If logging is disabled, a ``NullHandler`` is attached and
    third-party loggers are silenced.

    Args:
        settings: ``LoggingSettings`` object with all configuration parameters.
        logging_enabled: Whether general application logging is enabled.
        audit_enabled: Whether audit logging is enabled.
    """
    
    # Always configure structlog – it may still be used by other parts (e.g., audit)
    configure_structlog(settings)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    if logging_enabled:
        root_logger.setLevel(settings.get_log_level_int())
        _setup_console_handler(settings, root_logger)
        _setup_file_handler(settings, root_logger)
        _setup_error_handler(settings, root_logger)
    else:
        root_logger.setLevel(logging.CRITICAL)
        root_logger.addHandler(logging.NullHandler())

    # Configure audit logger
    if audit_enabled:
        _setup_audit_handler(settings)
    else:
        audit_logger = logging.getLogger("audit")
        audit_logger.handlers.clear()
        audit_logger.addHandler(logging.NullHandler())

    # Set the levels for third-party libraries (default CRITICAL if logging is off)
    sqlalchemy_level = logging.CRITICAL
    werkzeug_level = logging.CRITICAL
    
    if logging_enabled:
        sqlalchemy_level = getattr(logging, settings.sqlalchemy_log_level.upper(), logging.WARNING)
        logging.getLogger("sqlalchemy.engine").setLevel(sqlalchemy_level)

        werkzeug_level = getattr(logging, settings.werkzeug_log_level.upper(), logging.WARNING)
        logging.getLogger("werkzeug").setLevel(werkzeug_level)
    else:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.CRITICAL)
        logging.getLogger("werkzeug").setLevel(logging.CRITICAL)


    # Log that logging has been initialized (using extra fields to carry configuration)
    root_logger.info(
        "Logging has been initialized.",
        extra={
            "debug_mode": settings.debug,
            "log_level": settings.log_level_str,
            "log_to_console": settings.log_to_console,
            "log_to_file": settings.log_to_file,
            "log_dir": settings.log_dir if settings.log_to_file else None,
            "sqlalchemy_log_level": sqlalchemy_level,
            "werkzeug_log_level": werkzeug_level
        }
    )

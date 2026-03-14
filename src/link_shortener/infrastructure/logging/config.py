import logging
import logging.handlers
import os

from link_shortener.infrastructure.logging.settings import LoggingSettings
import structlog


def _replace_logger_name_with_module(logger, method_name, event_dict):
    """
    Replace the logger name with the module name if present.
    This allows us to show the module name in square brackets instead of the
    global logger name.
    """
    if 'module' in event_dict:
        event_dict['logger'] = event_dict.pop('module')
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
        _replace_logger_name_with_module,
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
        handler.setLevel(settings.get_log_level_int())
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
        handler.setLevel(settings.get_log_level_int())
        handler.setFormatter(logging.Formatter("%(message)s"))

        root_logger.addHandler(handler)



def setup_logging(settings: LoggingSettings, logging_enabled: bool, audit_enabled: bool) -> None:
    """
    Main entry point for logging configuration.

    Args:
        settings: LoggingSettings object containing all configuration parameters.
        general_enabled: Enable general application logging (to console/file).
        audit_enabled: Enable audit logging (to console/file).
    """

    # Always set up a structog for uniform formatting
    _configure_structlog(settings)

    # Setting general logging (root logger)
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    if logging_enabled:
        root_logger.setLevel(settings.get_log_level_int())
        _setup_console_handler(settings, root_logger)
        _setup_file_handler(settings, root_logger)
    else:
        root_logger.setLevel(logging.CRITICAL)
        root_logger.addHandler(logging.NullHandler())

    # Setting up an audit (a logger "audit")
    audit_logger = logging.getLogger("audit")
    audit_logger.handlers.clear()
    audit_logger.propagate = False  # do not pass on events in the root logger
    if audit_enabled:
        audit_logger.setLevel(settings.get_log_level_int())
        # Use the same handlers (console/file) as for general logging
        _setup_console_handler(settings, audit_logger)
        _setup_file_handler(settings, audit_logger)
    else:
        audit_logger.setLevel(logging.CRITICAL)
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


    # Log in the successful initialization (only if general logging is included)
    logger = structlog.get_logger(setup_logging.__module__)
    logger.info(
        "logging_initialized",
        debug_mode=settings.debug,
        log_level=settings.log_level_str,
        log_to_console=settings.log_to_console,
        log_to_file=settings.log_to_file,
        log_dir=settings.log_dir if settings.log_to_file else None,
        log_file=settings.log_file_path if settings.log_to_file else None,
        sqlalchemy_log_level=sqlalchemy_level,
        werkzeug_log_level=werkzeug_level
    )

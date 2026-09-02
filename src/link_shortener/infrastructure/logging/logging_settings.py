import logging
import os
from typing import Any, Callable


class LoggingSettings:
    """
    Configuration parameters for logging, extracted from Flask app config.

    This class holds all settings needed to configure logging, including
    directories, file names, log levels, and the chosen logger type.
    """

    def __init__(self,
                 log_dir: str,
                 log_file_name: str,
                 audit_log_filename: str,
                 error_log_filename: str,
                 log_date_format: str,
                 log_to_console: bool,
                 log_to_file: bool,
                 log_level_str: str,

                 debug: bool,

                 sqlalchemy_log_level: str,
                 werkzeug_log_level: str,

                 logger_type: str = "auto",
                 logging_enabled: bool = True,
                 audit_enabled: bool = True,
                 raise_on_write_failure: bool = True
    ):
        """
        Args:
            log_dir: Directory for log files.
            log_file_name: Base name for general log files (without extension).
            audit_log_filename: Base name for audit log files.
            error_log_filename: Base name for error log files.
            log_date_format: Date format for timestamps.
            log_to_console: Whether to log to stdout/stderr.
            log_to_file: Whether to log to rotating files.
            log_level_str: Log level as string (``"DEBUG"``, ``"INFO"``, …).
            debug: Whether debug mode is enabled.
            sqlalchemy_log_level: Log level for SQLAlchemy.
            werkzeug_log_level: Log level for Werkzeug.
            logger_type: Desired logger type (``"auto"``, ``"structlog"``,
                ``"standard"``, ``"null"``).
            logging_enabled: Whether the application's own journal is
                written at all. Here rather than passed to
                ``setup_logging`` beside the settings: it is a logging
                setting, read from ``LOGGING_ENABLED`` like every other
                name in this list, and a switch that travels by a second
                road is a switch that can disagree with itself -- which
                is what ``audit_enabled`` did.
            audit_enabled: Whether audit logging is enabled.
            raise_on_write_failure: Whether a failed write reaches the
                caller. True is for the web application, where
                ``FailoverService`` catches it and moves the work to
                another logger; a process without that service behind it
                asks for False, since there a raised write turns a lost
                log line into failed work.
        """

        self.log_dir = log_dir
        self.log_file_name = log_file_name
        self.audit_log_filename = audit_log_filename
        self.error_log_filename = error_log_filename
        self.log_date_format = log_date_format
        self.log_to_console = log_to_console
        self.log_to_file = log_to_file
        self.log_level_str = log_level_str.upper()

        self.debug = debug

        self.sqlalchemy_log_level = sqlalchemy_log_level
        self.werkzeug_log_level = werkzeug_log_level

        self.logger_type = logger_type
        self.logging_enabled = logging_enabled
        self.audit_enabled = audit_enabled
        self.raise_on_write_failure = raise_on_write_failure


    def get_log_level_int(self) -> int:
        """
        Convert the string log level to its integer representation.

        Returns:
            Integer log level (e.g., logging.DEBUG).
        """
        return getattr(logging, self.log_level_str, logging.INFO)

    @property
    def should_log_to_file(self) -> bool:
        """
        Check if file logging is enabled and a log directory is set.

        Returns:
            True if file logging should be used, False otherwise.
        """
        return self.log_to_file and bool(self.log_dir)

    @property
    def log_file_path(self) -> str:
        """
        Full path to the general log file (without rotation suffix).

        Returns:
            Absolute or relative path to the log file.
        """
        return os.path.join(self.log_dir, f"{self.log_file_name}.log")


def attribute_reader(config: Any) -> Callable[..., Any]:
    """
    Read a configuration object the way a mapping is read.

    ``app.config`` is a dictionary and a profile object is not, and the
    settings below have to be built from either.

    Args:
        config: A configuration object, such as ``BaseConfig``.

    Returns:
        A callable taking a name and a default.
    """
    def read(name: str, default: Any = None) -> Any:
        return getattr(config, name, default)

    return read


def logging_settings_from(
    read: Callable[..., Any], raise_on_write_failure: bool = True
) -> LoggingSettings:
    """
    Build the settings from whatever holds the configuration.

    One list of names, read by both processes that log. It was written
    twice for a while -- once in ``create_app`` and once for the Celery
    worker -- and two lists of the same names are two lists that drift: a
    setting added to one is silently absent in the other, and the worker
    goes on logging by a default nobody chose.

    The defaults here are the second copy of a truth ``BaseConfig`` already
    holds, and they cannot simply be dropped: ``read`` is handed whatever
    holds the configuration, and a name it cannot find has to resolve to
    something. So they are held to the profile's by a test that compares
    the two sets, the way ``PERMISSION_FOR`` is held to ``Journal``. One of
    them had already drifted -- ``LOG_FILENAME`` said
    ``link_shortener`` here and ``application`` there, which is the pair
    that decides which file the application writes and which file the
    journal viewer reads.

    Args:
        read: Callable taking a name and a default, the way
            ``app.config.get`` does. For a profile object,
            ``attribute_reader`` makes one.
        raise_on_write_failure: Passed through to ``LoggingSettings``.

    Returns:
        The settings ``setup_logging`` is given.
    """
    return LoggingSettings(
        log_dir=read("LOG_DIR", "logs"),
        log_file_name=read("LOG_FILENAME", "application"),
        audit_log_filename=read("AUDIT_LOG_FILENAME", "audit"),
        error_log_filename=read("ERROR_LOG_FILENAME", "error"),
        log_date_format=read("LOG_DATE_FORMAT", "%Y-%m-%d %H:%M:%S"),
        log_to_console=read("LOG_TO_CONSOLE", True),
        log_to_file=read("LOG_TO_FILE", False),
        log_level_str=read("LOG_LEVEL", "DEBUG"),
        debug=read("DEBUG", False),
        sqlalchemy_log_level=read("SQLALCHEMY_LOG_LEVEL", "WARNING"),
        werkzeug_log_level=read("WERKZEUG_LOG_LEVEL", "WARNING"),
        logger_type=read("LOGGER_TYPE", "auto"),
        logging_enabled=read("LOGGING_ENABLED", True),
        audit_enabled=read("AUDIT_ENABLED", True),
        raise_on_write_failure=raise_on_write_failure,
    )

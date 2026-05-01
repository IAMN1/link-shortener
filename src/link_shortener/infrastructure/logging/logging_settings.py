import logging
import os


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
                 audit_enabled: bool = True
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
            audit_enabled: Whether audit logging is enabled.
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
        self.audit_enabled = audit_enabled


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

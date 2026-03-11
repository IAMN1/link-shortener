import logging
import os


class LoggingSettings:
    """
    Configuration parameters for logging, extracted from Flask app config.
    """

    def __init__(self,
                 log_dir: str,
                 log_file_name: str,
                 log_date_format: str,
                 log_to_console: bool,
                 log_to_file: bool,
                 log_level_str: str,
                 debug: bool,
                 sqlalchemy_log_level: str,
                 werkzeug_log_level: str
    ):
        """
        Initialize logging settings.

        Args:
            log_dir: Directory for log files.
            log_file_name: Base name for log files (without extension).
            log_date_format: Date format for timestamps.
            log_to_console: Whether to log to console.
            log_to_file: Whether to log to file.
            log_level_str: Log level as string (e.g., "DEBUG").
            debug: Whether debug mode is enabled.
            sqlalchemy_log_level: Log level for SQLAlchemy.
            werkzeug_log_level: Log level for Werkzeug.
        """

        self.log_dir = log_dir
        self.log_file_name = log_file_name
        self.log_date_format = log_date_format
        self.log_to_console = log_to_console
        self.log_to_file = log_to_file
        self.log_level_str = log_level_str.upper()
        self.debug = debug
        self.sqlalchemy_log_level = sqlalchemy_log_level
        self.werkzeug_log_level = werkzeug_log_level


    def get_log_level_int(self) -> int:
        """Effective log level for the root logger."""
        return getattr(logging, self.log_level_str, logging.INFO)

    @property
    def should_log_to_file(self) -> bool:
        """Check if file logging is enabled and log directory is set."""
        return self.log_to_file and bool(self.log_dir)

    @property
    def log_file_path(self) -> str:
        """Full path to the log file (without rotation suffix)."""
        return os.path.join(self.log_dir, f"{self.log_file_name}.log")

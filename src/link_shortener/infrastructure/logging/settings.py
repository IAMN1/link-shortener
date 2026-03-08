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
                 debug: bool,
                 sqlalchemy_log_level: str,
                 werkzeug_log_level: str
                 ):
        """
        Initialize from Flask config dictionary.

        Args:
            flask_cfg: Flask app.config dictionary.
        """

        self.log_dir = log_dir
        self.log_file_name = log_file_name
        self.log_date_format = log_date_format
        self.log_to_console = log_to_console
        self.log_to_file = log_to_file
        self.debug = debug
        self.sqlalchemy_log_level = sqlalchemy_log_level
        self.werkzeug_log_level = werkzeug_log_level


    @property
    def log_level(self) -> int:
        """Effective log level for the root logger."""
        return logging.DEBUG if self.debug else logging.INFO

    @property
    def should_log_to_file(self) -> bool:
        """Check if file logging is enabled and log directory is set."""
        return self.log_to_file and bool(self.log_dir)

    @property
    def log_file_path(self) -> str:
        """Full path to the log file (without rotation suffix)."""
        return os.path.join(self.log_dir, f"{self.log_file_name}.log")
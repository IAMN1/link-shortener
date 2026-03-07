import logging
import os
from typing import Any, Dict

from link_shortener.infrastructure.config.base import BaseConfig


class LoggingSettings:
    """
    Configuration parameters for logging, extracted from Flask app config.
    """

    def __init__(self, flask_cfg: Dict[str, Any]):
        """
        Initialize from Flask config dictionary.

        Args:
            flask_cfg: Flask app.config dictionary.
        """

        self.log_dir: str = flask_cfg.get("LOG_DIR", BaseConfig.LOG_DIR)
        self.log_file_name: str = flask_cfg.get("LOG_FILENAME", BaseConfig.LOG_FILENAME)
        self.log_date_format: str = flask_cfg.get(
            "LOG_DATE_FORMAT", BaseConfig.LOG_DATE_FORMAT
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

    @property
    def log_file_path(self) -> str:
        """Full path to the log file (without rotation suffix)."""
        return os.path.join(self.log_dir, f"{self.log_file_name}.log")
from datetime import datetime
import json
import logging


class JSONFormatter(logging.Formatter):
    """
    Formatter that serialises log records to JSON.

    It produces a structured JSON object containing the timestamp, log level,
    logger name, event message, and all extra fields. Standard LogRecord attributes
    are excluded to keep the output clean.
    """

    def __init__(
        self, 
        date_format: str = "%Y-%m-%d %H:%M:%S", 
        ensure_ascii: bool = False
    ):
        """
        Initialize the JSON formatter.

        Args:
            date_format: Format string for timestamps.
            ensure_ascii: If True, all non‑ASCII characters are escaped.
        """
        
        super().__init__()
        self.date_format = date_format
        self.ensure_ascii = ensure_ascii
    
    def format(self, record: logging.LogRecord) -> str:
        """
        Format the log record as a JSON string.

        Args:
            record: The log record to format.

        Returns:
            A JSON string.
        """
        
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).strftime(self.date_format),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": record.getMessage(),
        }
        skip_keys = {
            'args', 'msg', 'created', 'asctime',
            'exc_info', 'exc_text', 'filename', 'funcName',
            'id', 'levelname', 'levelno', 'lineno', 'module',
            'msecs', 'name', 'pathname','process', 'processName',
            'relativeCreated', 'stack_info', 'thread', 'threadName'
        }
        for key, value in record.__dict__.items():
            if key in skip_keys or key in log_entry:
                continue

            # Check if the value is JSON‑serialisable
            try:
                json.dumps(value, ensure_ascii=self.ensure_ascii)
                log_entry[key] = value
            except (TypeError, ValueError):
                # Skip non‑serialisable values
                continue
        return json.dumps(log_entry, ensure_ascii=self.ensure_ascii)
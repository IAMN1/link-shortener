from datetime import datetime, timezone
import json
import logging

from link_shortener.infrastructure.logging.utils import (
    STANDARD_RECORD_ATTRS, UTC_SECONDS,
)


class JSONFormatter(logging.Formatter):
    """
    Formatter that serialises log records to JSON.

    It produces a structured JSON object containing the timestamp, log level,
    logger name, event message, and all extra fields. Standard LogRecord attributes
    are excluded to keep the output clean.
    """

    def __init__(self, ensure_ascii: bool = False):
        """
        Initialize the JSON formatter.

        Args:
            ensure_ascii: If True, all non-ASCII characters are escaped.
        """

        super().__init__()
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
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).strftime(UTC_SECONDS),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": record.getMessage(),
        }
        # Computed from a reference record, not enumerated: the hand-written
        # list this replaced predated Python 3.12 and let its new ``taskName``
        # attribute through, so every line carried ``"taskName": null``.
        skip_keys = STANDARD_RECORD_ATTRS
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
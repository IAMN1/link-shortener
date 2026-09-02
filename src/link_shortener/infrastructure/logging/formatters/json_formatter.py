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
            # The writer's own module where it named one, and the logger's
            # name otherwise. ``StandardLogger`` renames ``module`` to
            # ``module_name`` on its way in, because ``module`` collides
            # with a built-in LogRecord attribute; ``ConsoleFormatter``
            # displays the renamed value and the structlog chain folds its
            # own ``module`` into ``logger`` -- this was the one of the
            # three that did not, so the same record read
            # ``"logger": "...di.container"`` in the file and
            # ``[...read_journal]`` on the console beside it.
            "logger": getattr(record, "module_name", None) or record.name,
            "event": record.getMessage(),
        }
        # Computed from a reference record, not enumerated: the hand-written
        # list this replaced predated Python 3.12 and let its new ``taskName``
        # attribute through, so every line carried ``"taskName": null``.
        skip_keys = STANDARD_RECORD_ATTRS
        for key, value in record.__dict__.items():
            # ``module_name`` has already been read into ``logger``; left
            # in, every line would carry the same value under two names.
            if key in skip_keys or key in log_entry or key == "module_name":
                continue

            # Check if the value is JSON‑serialisable
            try:
                json.dumps(value, ensure_ascii=self.ensure_ascii)
                log_entry[key] = value
            except (TypeError, ValueError):
                # Skip non‑serialisable values
                continue

        # The traceback, which nothing here rendered. ``exc_info`` is in
        # ``STANDARD_RECORD_ATTRS``, so the loop above skips it, and this
        # formatter builds its output from scratch rather than through
        # ``super().format()`` -- so ``logger.exception("...")`` under
        # ``LOGGER_TYPE=standard`` wrote the message and no stack at all,
        # while ``Logger.exception``'s own docstring promises one and the
        # structlog chain beside it records ``exc_info``. Measured: an
        # exception raised and logged came out as
        # ``{"event": "something blew up"}`` with no type, no message and
        # no frames -- in ``error.log``, which is the file an operator
        # opens for exactly that.
        #
        # Rendered rather than passed through: the tuple holds a live
        # exception and a traceback object, neither of which is JSON.
        if record.exc_info:
            log_entry["exc_info"] = self.formatException(record.exc_info)
        elif record.exc_text:
            log_entry["exc_info"] = record.exc_text

        return json.dumps(log_entry, ensure_ascii=self.ensure_ascii)

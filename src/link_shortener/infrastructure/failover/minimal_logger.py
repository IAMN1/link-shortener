"""
Minimal logger used before the application's full logging infrastructure is ready.

It prints messages to stderr with a timestamp, but any class using it
can be injected with a custom implementation for testing or later upgrade.
"""


import datetime
import sys

from link_shortener.infrastructure.logging.utils import UTC_SECONDS


class MinimalLogger:
    """
    Simple logger that writes to stderr.

    This logger is intended for bootstrapping scenarios where the full
    structured logging system is not yet available. It does not depend on
    any external libraries and provides basic ``info``, ``warning``, and
    ``error`` methods.
    """

    def info(self, message: str) -> None:
        """
        Log an informational message.

        Args:
            message: The message to log.
        """
        self._emit("INFO", message)

    def warning(self, message: str) -> None:
        """
        Log a warning message.

        Args:
            message: The warning message to log.
        """
        self._emit("WARNING", message)

    def error(self, message: str) -> None:
        """
        Log an error message.

        Args:
            message: The error message to log.
        """
        self._emit("ERROR", message)

    def _emit(self, level: str, message: str) -> None:
        """
        Format and write a log entry to stderr.

        Args:
            level: Severity label (e.g. ``"INFO"``).
            message: The log message text.
        """
        # UTC, and saying so, for the reason given in ``json_formatter``:
        # this logger writes the lines around a failure, and they are read
        # beside the journal's own. Two of them stamped in different zones
        # put the cause after the effect.
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime(UTC_SECONDS)
        print(f"{timestamp} [{level}] {message}", file=sys.stderr)

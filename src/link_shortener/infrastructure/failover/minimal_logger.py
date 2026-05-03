"""
Minimal logger used before the application's full logging infrastructure is ready.

It prints messages to stderr with a timestamp, but any class using it
can be injected with a custom implementation for testing or later upgrade.
"""


import datetime
import sys


class MinimalLogger:
    """Simple logger that writes to stderr."""

    def info(self, message: str) -> None:
        """Log an informational message."""
        self._emit("INFO", message)

    def warning(self, message: str) -> None:
        """Log a warning message."""
        self._emit("WARNING", message)

    def error(self, message: str) -> None:
        """Log an error message."""
        self._emit("ERROR", message)

    def _emit(self, level: str, message: str) -> None:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"{timestamp} [{level}] {message}", file=sys.stderr)

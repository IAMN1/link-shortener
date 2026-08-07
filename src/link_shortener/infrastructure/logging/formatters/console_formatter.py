import logging

from link_shortener.infrastructure.logging.utils import STANDARD_RECORD_ATTRS


class ConsoleFormatter(logging.Formatter):
    """
    Formatter for console output in 'standard' logger mode.

    It produces a human-readable line:
        timestamp - [module_name] - message [key1=value1 key2=value2 ...]
    where module_name is taken from the record's 'module_name' attribute (if present)
    or falls back to the logger name.

    The formatter excludes standard LogRecord attributes and prints all extra fields
    as key=value pairs.
    """
    
    def __init__(self, fmt: str = "%(asctime)s - [%(name)s] - %(message)s", datefmt: str = "%Y-%m-%d %H:%M:%S"):
        """
        Initialize the console formatter.

        Args:
            fmt: Format string (used only for the base part).
            datefmt: Date format for timestamps.
        """
        super().__init__(fmt, datefmt)
        self.datefmt = datefmt
        # Computed from a reference record rather than enumerated: the
        # list this replaced predated Python 3.12 and let its new
        # ``taskName`` attribute through, so every console line ended in
        # ``- [taskName=None]``.
        self.standard_attrs = STANDARD_RECORD_ATTRS
    
    def format(self, record: logging.LogRecord) -> str:
        """
        Format the log record into a human_readable string.

        Args:
            record: The log record to format.

        Returns:
            Formatted string.
        """

        # Determine the display name (use module_name if present)
        display_name = getattr(record, 'module_name', None) or record.name
        timestamp = self.formatTime(record, self.datefmt)
        msg = record.getMessage()
        base = f"{timestamp} - [{display_name}] - {msg}"
        
        # Collect extra fields that are not standard attributes
        extra_items = []
        for key, value in record.__dict__.items():
            if key in self.standard_attrs or key == "module_name":
                continue

            if isinstance(value, (str, int, float, bool)):
                extra_items.append(f"{key}={value}")
            else:
                # Use repr for non‑primitive types
                extra_items.append(f"{key}={repr(value)}")
        
        if extra_items:
            base += f" - [{' - '.join(extra_items)}]"
        return base

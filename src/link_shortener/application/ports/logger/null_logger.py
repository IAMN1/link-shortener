from typing import Any, Optional

from link_shortener.application.ports.logger.logger import Logger



class NullLogger(Logger):
    """
    Null-object implementation of Logger.

    All log messages are silently discarded.
    Used when logging is disabled or as a fallback.
    """

    def debug(self, message: str, **kwargs: Any) -> None:
        """No-op."""
        pass

    def info(self, message: str, **kwargs: Any) -> None:
        """No-op."""
        pass

    def warning(self, message: str, **kwargs: Any) -> None:
        """No-op."""
        pass

    def error(self, message: str, **kwargs: Any) -> None:
        """No-op."""
        pass

    def exception(
        self, message: str, exc_info: Optional[Exception] = None, **kwargs: Any
    ) -> None:
        """No-op."""
        pass
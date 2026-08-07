"""
Structlog adapter for application logs.

This module contains ``StructLogger`` which wraps a structlog ``BoundLogger``
and implements the domain ``Logger`` interface.
"""

from typing import Any, Optional

import structlog

from link_shortener.application import Logger


class StructLogger(Logger):
    """Adapter for structlog, implementing the ``Logger`` interface.

    This adapter wraps a ``structlog.BoundLogger`` and provides the ``bind()``
    method to create new loggers with additional contextual fields.

    Attributes:
        _logger: The underlying structlog ``BoundLogger`` instance.
    """

    def __init__(self, name: Optional[str] = None, bound_logger=None):
        """Initialise the structlog logger.

        Args:
            name: Logger name (defaults to ``__name__`` of the caller if None).
            bound_logger: An existing ``BoundLogger``; if ``None``, a new one
                is created.
        """
        if bound_logger is None:
            self._logger = structlog.get_logger(name or __name__).bind()
        else:
            self._logger = bound_logger

    def bind(self, **kwargs) -> "StructLogger":
        """Return a new ``StructLogger`` with additional bound fields.

        Args:
            **kwargs: Fields to bind.

        Returns:
            A new ``StructLogger`` instance with the combined bound fields.
        """
        new_logger = self._logger.bind(**kwargs)
        return StructLogger(bound_logger=new_logger)

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log a debug message.

        Args:
            message: The log message.
            **kwargs: Additional structured data.
        """
        self._logger.debug(message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        """Log an informational message.

        Args:
            message: The log message.
            **kwargs: Additional structured data.
        """
        self._logger.info(message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log a warning message.

        Args:
            message: The log message.
            **kwargs: Additional structured data.
        """
        self._logger.warning(message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        """Log an error message.

        Args:
            message: The log message.
            **kwargs: Additional structured data.
        """
        self._logger.error(message, **kwargs)

    def exception(
        self, message: str, exc_info: Optional[Exception] = None, **kwargs: Any
    ) -> None:
        """Log an exception message with traceback.

        Args:
            message: The log message.
            exc_info: The exception instance; if ``None`` the current exception
                is captured.
            **kwargs: Additional structured data.
        """
        kwargs["exc_info"] = exc_info
        self._logger.exception(message, **kwargs)

    def is_healthy(self) -> bool:
        """Check whether the logger is operational.

        Returns:
            ``True`` if a simple debug log call succeeds, ``False`` otherwise.
        """
        try:
            self._logger.debug("health_check")
            return True
        except Exception:
            return False

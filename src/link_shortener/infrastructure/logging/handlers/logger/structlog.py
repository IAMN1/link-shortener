from typing import Any, Optional

import structlog

from link_shortener.application import Logger


class StructLogger(Logger):
    """
    Adapter for structlog, implementing the Logger interface.

    This adapter wraps a structlog.BoundLogger and provides the bind() method
    to create new loggers with additional contextual fields.
    """

    def __init__(self, name: Optional[str] = None, bound_logger=None):
        """
        Initialize the structlog logger.

        Args:
            name: Logger name (defaults to __name__ of caller if None).
            bound_logger: If provided, used as a base logger with fields already bound.
        """
        if bound_logger is None:
            # Create a BoundLogger immediately (not a lazy proxy)
            self._logger = structlog.get_logger(name or __name__).bind()
        else:
            self._logger = bound_logger

    def bind(self, **kwargs) -> "StructLogger":
        """
        Return a new StructLogger with the bound fields.

        Args:
            **kwargs: Fields to bind.

        Returns:
            A new StructLogger instance with the additional bound fields.
        """
        new_logger = self._logger.bind(**kwargs)
        return StructLogger(bound_logger=new_logger)


    def debug(self, message: str, **kwargs: Any) -> None:
        self._logger.debug(message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        self._logger.info(message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        self._logger.warning(message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self._logger.error(message, **kwargs)

    def exception(
        self, message: str, exc_info: Optional[Exception] = None, **kwargs: Any
    ) -> None:
        kwargs["exc_info"] = exc_info
        self._logger.exception(message, **kwargs)

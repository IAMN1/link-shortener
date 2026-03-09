from typing import Any, Optional

import structlog

from link_shortener.application import Logger


class StructLogger(Logger):
    """
    Adapter for structlog, implementing the Logger interface.
    """

    def __init__(self, name: Optional[str] = None):
        """
        Initialize the structlog logger.

        Args:
            name: Logger name (defaults to __name__ of caller if None).
        """
        self._base_logger = structlog.get_logger(name or __name__)


    def _log(self, level: str, message: str, **kwargs):
        """Internal method to log at given level with optional module binding."""

        module = kwargs.pop("module", None)
        logger = self._base_logger

        if module:
            logger = logger.bind(module=module)

        getattr(logger, level)(message, **kwargs)


    def debug(self, message: str, **kwargs: Any) -> None:
        self._log("debug", message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        self._log("info", message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        self._log("warning", message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self._log("error", message, **kwargs)

    def exception(
        self, message: str, exc_info=Optional[Exception], **kwargs: Any
    ) -> None:
        kwargs["exc_info"] = exc_info
        self._log("exception", message, **kwargs)

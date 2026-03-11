import logging
from typing import Any, Optional
from link_shortener.application import Logger


class StandardLogger(Logger):
    """
    Adapter for the standard Python logging module.

    This implementation wraps a standard logging.Logger and formats
    structured data as key-value pairs appended to the message.
    """

    def __init__(self, name: str):
        """
        Initialize the logger.

        Args:
            name: Logger name.
        """
        self._logger = logging.getLogger(name)    

    def _log(self, level: str, message: str, **kwargs):
        """Internal method to log with extra data."""

        module = kwargs.pop("module", None)

        # Add module to the message or to extra
        log_method = getattr(self._logger, level)
        extra = kwargs.copy()

        if module:
            extra["module"] = module

        # Standard logger's extra parameter can be used, but not all handlers respect it.
        # To be safe, we'll just append module to the message if present.
        if module:
            message = f"[{module}] {message}"
        if extra:
            log_method(f"{message} - {extra}")
        else:
            log_method(message)


    def debug(self, message: str, **kwargs: Any) -> None:
        self._log("debug", message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        self._log("info", message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        self._log("warning", message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self._log("error", message, **kwargs)

    def exception(
        self, message: str, exc_info: Optional[Exception] = None, **kwargs: Any
    ) -> None:
        kwargs["exc_info"] = exc_info
        self._log("exception", message, **kwargs)

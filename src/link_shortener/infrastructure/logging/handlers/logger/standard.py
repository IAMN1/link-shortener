import logging
from typing import Any, Dict, Optional
from link_shortener.application import Logger


class StandardLogger(Logger):
    """
    Adapter for the standard Python logging module.

    This implementation wraps a standard `logging.Logger` and passes structured
    data via the `extra` keyword argument. It also supports binding of additional
    fields that are automatically added to every log call.

    Fields bound via `bind()` are stored in `_bound_fields` and merged with the
    percall keyword arguments before logging.
    """

    def __init__(self, name: str, bound_fields: Optional[Dict[str, Any]] = None):
        """
        Initialize the logger.

        Args:
            name: Logger name (e.g., module name).
            bound_fields: A dictionary of fields bound to the logger.
        """
        self._logger = logging.getLogger(name)
        self._bound_fields = bound_fields if bound_fields else {}
    
    def bind(self, **kwargs) -> "StandardLogger":
        """
        Return a new StandardLogger with additional bound fields.

        Args:
            **kwargs: Fields to bind.

        Returns:
            A new StandardLogger instance combining existing and new bound fields.
        """
        new_bound = {**self._bound_fields, **kwargs}
        return StandardLogger(self._logger.name, bound_fields=new_bound)

    def _log(self, level: str, message: str, **kwargs):
        """
        Internal method that performs the actual logging.

        Args:
            level: Log level (e.g., "info", "error").
            message: The log message.
            **kwargs: Additional structured fields to include in the log record.
        """
        
        extra = {**self._bound_fields, **kwargs}

        # Rename 'module' to 'module_name' to avoid conflict with built‑in LogRecord attribute.
        module = extra.pop("module", None)

        if module:
            extra["module_name"] = module
        
        log_method = getattr(self._logger, level)
        log_method(message, extra=extra)


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
        """
        Log an exception with traceback.

        Args:
            message: Log message.
            exc_info: Exception to log (if None, current exception is captured).
            **kwargs: Additional structured fields.
        """
        kwargs["exc_info"] = exc_info
        self._log("exception", message, **kwargs)

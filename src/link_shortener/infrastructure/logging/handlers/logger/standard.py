"""
Standard Python logging adapter for application logs.

This module contains ``StandardLogger`` which wraps the standard library's
``logging.Logger`` and implements the domain ``Logger`` interface.
"""

import logging
from typing import Any, Dict, Optional

from link_shortener.application import Logger


class StandardLogger(Logger):
    """Adapter for the standard Python logging module.

    This implementation passes structured data via the ``extra`` keyword
    argument and supports field binding through the ``bind()`` method.

    Attributes:
        _logger: The underlying ``logging.Logger`` instance.
        _bound_fields: Dictionary of fields bound to this logger instance.
    """

    def __init__(self, name: str, bound_fields: Optional[Dict[str, Any]] = None):
        """Initialise the logger.

        Args:
            name: Logger name (e.g. module name).
            bound_fields: A dictionary of fields to attach to every log call.
        """
        self._logger = logging.getLogger(name)
        self._bound_fields = bound_fields if bound_fields else {}

    def bind(self, **kwargs) -> "StandardLogger":
        """Return a new ``StandardLogger`` with additional bound fields.

        Args:
            **kwargs: Fields to bind.

        Returns:
            A new ``StandardLogger`` instance combining existing and new fields.
        """
        new_bound = {**self._bound_fields, **kwargs}
        return StandardLogger(self._logger.name, bound_fields=new_bound)

    def _log(self, level: str, message: str, **kwargs):
        """Internal method that performs the actual logging.

        Args:
            level: Log level as a string (e.g. ``"info"``, ``"error"``).
            message: The log message.
            **kwargs: Additional structured fields to include.
        """
        extra = {**self._bound_fields, **kwargs}

        # Avoid conflict with the built‑in ``module`` attribute by renaming
        module = extra.pop("module", None)
        if module:
            extra["module_name"] = module
        
        # For the 'exception' level, logging.Logger.exception requires
        # exc_info=True or an exception instance.  We call the appropriate
        # method and pass exc_info separately.
        if level == "exception":
            exc_info = extra.pop("exc_info", True)  # defaults to current exception
            self._logger.exception(message, extra=extra, exc_info=exc_info)
        else:
            log_method = getattr(self._logger, level)
            log_method(message, extra=extra)

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log a debug message.

        Args:
            message: The log message.
            **kwargs: Additional structured data.
        """
        self._log("debug", message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        """Log an informational message.

        Args:
            message: The log message.
            **kwargs: Additional structured data.
        """
        self._log("info", message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log a warning message.

        Args:
            message: The log message.
            **kwargs: Additional structured data.
        """
        self._log("warning", message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        """Log an error message.

        Args:
            message: The log message.
            **kwargs: Additional structured data.
        """
        self._log("error", message, **kwargs)

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
        kwargs["exc_info"] = exc_info if exc_info is not None else True
        self._log("exception", message, **kwargs)

    def is_healthy(self) -> bool:
        """Check whether the logger is operational.

        Returns:
            ``True`` if the logger has handlers and can write a health-check
            message, ``False`` otherwise.
        """
        if not self._logger.handlers:
            return False
        try:
            test_logger = logging.getLogger(self._logger.name + "._health_test")
            test_logger.handlers = self._logger.handlers
            test_logger.propagate = False
            test_logger.setLevel(logging.DEBUG)
            test_logger.debug("health_check")
            return True
        except Exception:
            return False
        finally:
            logging.Logger.manager.getLogger(
                self._logger.name + "._health_test"
            ).handlers = []

"""
Structlog adapter for application logs.

This module contains ``StructLogger`` which wraps a structlog ``BoundLogger``
and implements the domain ``Logger`` interface.
"""

import logging
from typing import Any, Optional

import structlog

from link_shortener.application import Logger
from link_shortener.infrastructure.logging.utils import (
    HEALTH_PROBE_FIELDS, HEALTH_PROBE_MESSAGE, probe_level,
)


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
        # Kept beside the bound logger because ``is_healthy`` needs it: the
        # level a probe has to be written at is a property of the standard
        # library logger underneath, and structlog's own object does not
        # offer it without reaching into a private attribute.
        self._name = name or __name__
        if bound_logger is None:
            self._logger = structlog.get_logger(self._name).bind()
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
        # The name travels with the copy. Left behind, every bound logger
        # answered ``is_healthy`` about this module's name rather than
        # about the chain it writes to.
        return StructLogger(name=self._name, bound_logger=new_logger)

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
        self, message: str, exc_info: Any = True, **kwargs: Any
    ) -> None:
        """Log an exception message with traceback.

        Args:
            message: The log message.
            exc_info: ``True`` takes the exception being handled; an
                exception instance is rendered instead; ``None`` asks for
                no traceback, because the renderer skips a falsy value.
            **kwargs: Additional structured data.
        """
        kwargs["exc_info"] = exc_info
        self._logger.exception(message, **kwargs)

    def is_healthy(self) -> bool:
        """Check whether the logger is operational.

        Asked of the hierarchy first, as the two ``standard`` adapters
        ask it: a write that reaches no handler raises nothing, so a
        probe that only writes answers ``True`` for a chain going
        nowhere. Measured with every handler removed and structlog
        configured as ``bootstrap`` configures it, the four
        implementations answered the same question two ways --
        ``StandardLogger`` and ``StandardAuditLogger`` ``False``, this
        one and ``StructlogAuditLogger`` ``True``. They are
        interchangeable by construction: the failover service hands the
        work between them on this answer, so one state has to have one
        answer, or which defect the service notices depends on
        ``LOGGER_TYPE``.

        Written at the level this chain actually passes records at, for
        the reason ``probe_level`` gives: structlog hands the record to
        the standard library, where a ``DEBUG`` probe was dropped by the
        handler's own level test before it could fail on a broken one.

        Returns:
            ``True`` if a handler is reachable from this logger and a
            probe record can be written, ``False`` otherwise.
        """
        if not logging.getLogger(self._name).hasHandlers():
            return False

        try:
            self._logger.log(
                probe_level(self._name), HEALTH_PROBE_MESSAGE,
                **HEALTH_PROBE_FIELDS,
            )
            return True
        except Exception:
            return False

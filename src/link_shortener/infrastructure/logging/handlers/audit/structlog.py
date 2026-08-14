"""
Structlog adapter for audit events.

This module contains ``StructlogAuditLogger`` which implements the ``AuditLogger``
interface using the structlog library. It provides structured logging and
supports field binding.
"""

from typing import Any, Dict

import structlog

from link_shortener.application import AuditLogger
from link_shortener.infrastructure.logging.utils import mask_url


class StructlogAuditLogger(AuditLogger):
    """Audit logger implementation using structlog.

    This is the preferred implementation when structlog is available.
    It supports ``bind`` to attach contextual fields and uses a
    ``BoundLogger`` for efficient structured logging.

    Attributes:
        _logger: The underlying structlog ``BoundLogger``.
        _bound_fields: Dictionary of fields bound to this logger instance.
    """

    def __init__(self, bound_logger=None, bound_fields: Dict[str, Any] = None):
        """Initialise the structlog audit logger.

        Args:
            bound_logger: An existing structlog ``BoundLogger``; if ``None``,
                a new logger for the ``"audit"`` namespace is created.
            bound_fields: Initial fields to bind.
        """
        self._bound_fields = bound_fields or {}
        if bound_logger is None:
            self._logger = structlog.get_logger("audit")
        else:
            self._logger = bound_logger

    def bind(self, **kwargs) -> "StructlogAuditLogger":
        """Return a new audit logger with additional bound fields.

        Args:
            **kwargs: Fields to bind (e.g. request_id, remote_addr).

        Returns:
            A new ``StructlogAuditLogger`` with the combined bound fields.
        """
        new_bound = {**self._bound_fields, **kwargs}
        new_logger = self._logger.bind(**kwargs)
        return StructlogAuditLogger(
            bound_logger=new_logger, bound_fields=new_bound
        )

    def _build_data(
        self,
        event_type: str,
        short_code: str,
        original_url: str,
        **kwargs
    ) -> dict:
        """Construct the dictionary of log fields for an audit event.

        The binding goes in first and everything else wins over it, which is
        how the sibling adapter ``StandardAuditLogger`` merges
        (``{**bound, **call}``) and how the library underneath resolves the
        same collision: ``event_dict = self._context.copy()`` and then
        ``event_dict.update(**event_kw)`` (``structlog._base``).

        Applied last, the binding would overwrite not only a
        field the call named but the event's own three: a logger bound with
        ``original_url`` put that value into the record in place of
        ``mask_url(original_url)``, so binding was a way round the masking.
        ``event_type`` and ``short_code`` went the same way, which is a
        record of one event filed under another.

        Args:
            event_type: Type of the audit event.
            short_code: Short code of the link.
            original_url: Original URL (will be masked).
            **kwargs: Additional contextual fields.

        Returns:
            Dictionary containing the event type, short code, masked
            original URL, all bound fields, and any extra kwargs.
        """
        data = dict(self._bound_fields)
        data.update({
            "event_type": event_type,
            "short_code": short_code,
            "original_url": mask_url(original_url),
        })
        data.update(kwargs)
        return data

    def log_url_created(self, short_code: str, original_url: str, **kwargs) -> None:
        """Log a URL creation event.

        Args:
            short_code: The generated short code.
            original_url: The original long URL.
            **kwargs: Additional context (e.g. batch_id, is_new).
        """
        data = self._build_data(
            event_type="URL_CREATED",
            short_code=short_code,
            original_url=original_url,
            **kwargs
        )
        self._logger.info("Url created successfully", **data)

    def log_url_accessed(self, short_code: str, original_url: str, **kwargs) -> None:
        """Log a URL access (redirect) event.

        Args:
            short_code: The short code that was accessed.
            original_url: The original URL to which the user was redirected.
            **kwargs: Additional context (e.g. clicks count).
        """
        data = self._build_data(
            event_type="URL_ACCESSED",
            short_code=short_code,
            original_url=original_url,
            **kwargs
        )
        self._logger.info("Url accessed successfully", **data)

    def log_url_deleted(self, short_code: str, original_url: str, **kwargs) -> None:
        """Log a URL deletion event.

        Args:
            short_code: The short code of the deleted link.
            original_url: The original long URL that was shortened.
            **kwargs: Additional context (e.g. request_id, remote_addr).
        """
        data = self._build_data(
            event_type="URL_DELETED",
            short_code=short_code,
            original_url=original_url,
            **kwargs
        )
        self._logger.info("Url deleted successfully", **data)

    def is_healthy(self) -> bool:
        """Check whether the audit logger is operational.

        Returns:
            ``True`` if a simple debug log call succeeds, ``False`` otherwise.
        """
        try:
            self._logger.debug("health_check")
            return True
        except Exception:
            return False

"""
Standard Python logging adapter for audit events.

This module provides the ``StandardAuditLogger`` which implements the
``AuditLogger`` interface using the standard library's ``logging`` module.
It can be used as a primary or fallback audit logger.
"""

import logging
from typing import Any, Dict

from link_shortener.application import AuditLogger
from link_shortener.infrastructure.logging.utils import mask_url


class StandardAuditLogger(AuditLogger):
    """Audit logger using the standard ``logging`` module.

    Bound fields are stored internally and passed via the ``extra`` keyword
    argument on every log call. URL values are automatically masked for
    privacy when written to the log.

    Attributes:
        _logger: The underlying ``logging.Logger`` instance.
        _bound_fields: Dictionary of contextual fields bound to the logger.
    """

    def __init__(self, name: str = "audit", bound_fields: Dict[str, Any] = None):
        """Initialise the standard audit logger.

        Args:
            name: Name of the logger (default ``"audit"``).
            bound_fields: Initial dictionary of bound fields.
        """
        self._logger = logging.getLogger(name)
        self._bound_fields = bound_fields or {}

    def bind(self, **kwargs) -> "StandardAuditLogger":
        """Return a new audit logger with additional bound fields.

        Args:
            **kwargs: Fields to bind (e.g. request_id, remote_addr).

        Returns:
            A new ``StandardAuditLogger`` instance with the combined bound fields.
        """
        return StandardAuditLogger(
            name=self._logger.name,
            bound_fields={**self._bound_fields, **kwargs}
        )

    def _log(self, event: str, **kwargs):
        """Internal logging helper.

        Args:
            event: Event name (e.g. ``"URL_CREATED"``).
            **kwargs: Structured data to include in the log record.
        """
        all_fields = {**self._bound_fields, **kwargs}
        self._logger.info(event, extra=all_fields)

    def _build_data(
        self,
        event_type: str,
        short_code: str,
        original_url: str,
        **kwargs
    ) -> dict:
        """Construct the dictionary of log fields for an audit event.

        Args:
            event_type: Type of the audit event.
            short_code: Short code of the link.
            original_url: Original URL (will be masked).
            **kwargs: Additional contextual fields.

        Returns:
            Dictionary containing the event type, short code, masked
            original URL, and any extra fields.
        """
        data = {
            "event_type": event_type,
            "short_code": short_code,
            "original_url": mask_url(original_url),
        }
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
        self._log("Url created successfully", **data)

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
        self._log("Url accessed successfully", **data)

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
        self._log("Url deleted successfully", **data)

    def is_healthy(self) -> bool:
        """Check whether the audit logger is operational.

        Returns:
            ``True`` if the logger has handlers and can write a health-check
            message without error, ``False`` otherwise.
        """
        if not self._logger.handlers:
            return False
        try:
            # Create a temporary logger sharing the same handlers
            test_logger = logging.getLogger(self._logger.name + "._health_test")
            test_logger.handlers = self._logger.handlers
            test_logger.propagate = False
            test_logger.setLevel(logging.DEBUG)
            test_logger.debug("health_check")
            return True
        except Exception:
            return False
        finally:
            # Clean up temporary logger to avoid memory leaks
            logging.Logger.manager.getLogger(
                self._logger.name + "._health_test"
            ).handlers = []

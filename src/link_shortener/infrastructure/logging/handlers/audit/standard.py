import logging
from typing import Any, Dict
from link_shortener.application import AuditLogger
from link_shortener.infrastructure.logging.utils import mask_url


class StandardAuditLogger(AuditLogger):
    """
    Audit logger using the standard Python `logging` module.

    This implementation is used as a fallback when `structlog` is unavailable
    or explicitly selected. It stores bound fields in `_bound_fields` and
    passes them via the `extra` keyword argument.
    """

    def __init__(self, name: str = "audit", bound_fields: Dict[str, Any] = None):
        """
        Initialize the audit logger.

        Args:
            name: Name of the logger (default: "audit").
            bound_fields: Initial fields to bind to the logger
        """
        self._logger = logging.getLogger(name)
        self._bound_fields = bound_fields or {}
    
    def bind(self, **kwargs) -> "StandardAuditLogger":
        """
        Return a new audit logger with the provided fields bound.

        Args:
            **kwargs: Fields to bind (e.g., request_id, remote_addr).

        Returns:
            A new StandardAuditLogger instance with combined bound fields.
        """
        return StandardAuditLogger(self._logger.name, {**self._bound_fields, **kwargs})
    
    def _log(self, event: str, **kwargs):
        """
        Internal logging method.

        Args:
            event: Event name (e.g., "url_created").
            **kwargs: Structured data to include in the log.
        """
        all_fields = {**self._bound_fields, **kwargs}
        self._logger.info(event, extra=all_fields)
    
    def _build_data(self, event_type: str, short_code: str, original_url: str, **kwargs) -> dict:
        """
        Build a dictionary of log fields.

        Args:
            event_type: Type of event (e.g., "URL_CREATED").
            short_code: Short code of the link.
            original_url: Original URL (will be masked if too long).
            **kwargs: Additional fields.

        Returns:
            Dictionary containing event_type, short_code, masked original_url,
            and any extra kwargs.
        """
        data = {
            "event_type": event_type,
            "short_code": short_code,
            "original_url": mask_url(original_url),
        }
        data.update(kwargs)
        return data
    
    def log_url_created(self, short_code: str, original_url: str, **kwargs) -> None:
        """
        Log a URL creation event.

        Args:
            short_code: The generated short code.
            original_url: The original long URL.
            **kwargs: Additional context (e.g., batch_id, is_new).
        """

        data = self._build_data(
            event_type="URL_CREATED",
            short_code=short_code,
            original_url=original_url,
            **kwargs
        )
        self._log("Url created successfully", **data)
    
    def log_url_accessed(self, short_code: str, original_url: str, **kwargs) -> None:
        """
        Log a URL access (redirect) event.

        Args:
            short_code: The short code that was accessed.
            original_url: The original URL to which the user was redirected.
            **kwargs: Additional context (e.g., clicks count)
        """

        data = self._build_data(
            event_type="URL_ACCESSED",
            short_code=short_code,
            original_url=original_url,
            **kwargs
        )
        self._log("Url accessed successfully", **data)
    
    def log_url_deleted(self, short_code: str, original_url: str, **kwargs) -> None:
        """
        Log a URL deletion event.

        Args:
            short_code: The short code of the deleted link.
            original_url: The original long URL that was shortened.
            **kwargs: Additional context (e.g., request_id, remote_addr).
        """
        data = self._build_data(
            event_type="URL_DELETED",
            short_code=short_code,
            original_url=original_url,
            **kwargs
        )
        self._log("Url deleted successfully", **data)

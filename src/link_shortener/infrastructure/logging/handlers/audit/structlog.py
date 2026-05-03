from typing import Any, Dict
from link_shortener.infrastructure.logging.utils import mask_url
import structlog

from link_shortener.application import AuditLogger


class StructlogAuditLogger(AuditLogger):
    """
    Audit logger implementation using structlog.

    This is the preferred implementation when structlog is available.
    It supports `bind` to attach contextual fields and uses structlog's
    `BoundLogger` for efficient structured logging.
    """

    def __init__(self, bound_logger=None, bound_fields: Dict[str, Any] = None):
        """
        Initialize the structlog audit logger.

        Args:
            bound_logger: An existing structlog BoundLogger (optional).
            bound_fields: Initial fields to bind (used when creating a new logger).
        """
        self._bound_fields = bound_fields or {}
        if bound_logger is None:
            self._logger = structlog.get_logger("audit")
        else:
            self._logger = bound_logger
    
    def bind(self, **kwargs) -> "StructlogAuditLogger":
        """
        Return a new audit logger with the provided fields bound.

        Args:
            **kwargs: Fields to bind (e.g., request_id, remote_addr).

        Returns:
            A new StructlogAuditLogger instance with combined bound fields.
        """
        new_bound = {**self._bound_fields, **kwargs}
        new_logger = self._logger.bind(**kwargs)
        return StructlogAuditLogger(bound_logger=new_logger, bound_fields=new_bound)
    
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
            any extra kwargs, and all bound fields.
        """
        data = {
            "event_type": event_type,
            "short_code": short_code,
            "original_url": mask_url(original_url),
        }
        data.update(kwargs)
        data.update(self._bound_fields)
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
        self._logger.info("Url created successfully", **data)


    def log_url_accessed(self, short_code: str, original_url: str, **kwargs) -> None:
        """
        Log a URL access (redirect) event.

        Args:
            short_code: The short code that was accessed.
            original_url: The original URL to which the user was redirected.
            **kwargs: Additional context (e.g., clicks count).
        """

        data = self._build_data(
            event_type="URL_ACCESSED",
            short_code=short_code,
            original_url=original_url,
            **kwargs
        )
        self._logger.info("Url accessed successfully", **data)

    def log_url_deleted(self, short_code, original_url, **kwargs) -> None:
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
        self._logger.info("Url deleted successfully", **data)
    
    def is_healthy(self) -> bool:
        """"""
        try:
            self._logger.debug("health_check")
            return True
        except Exception:
            return False

import logging
from link_shortener.application import AuditLogger, RequestContext
from link_shortener.domain import Link
from link_shortener.infrastructure.logging.utils import mask_url


class StandardAuditLogger(AuditLogger):
    """
    Audit logger using standard logging module (fallback when structlog is unavailable).

    This implementation uses the built-in `logging` module and passes structured
    data via the `extra` keyword argument. It is used as a fallback when structlog
    cannot be used (e.g., due to import errors or configuration issues).
    """

    def __init__(self, name: str = "audit"):
        """
        Initialize the audit logger.

        Args:
            name: Name of the logger (default: "audit").
        """
        self._logger = logging.getLogger(name)
    
    def _log(self, event: str, **kwargs):
        """
        Internal method to log an audit event with extra fields.

        Args:
            event: The event name (e.g., "url_created").
            **kwargs: Additional fields to include in the log record's `extra`.
        """
        self._logger.info(event, extra=kwargs)
    
    def log_url_created(self, link: Link, context: RequestContext, **kwargs) -> None:
        """
        Log a URL creation event.

        Args:
            link: The newly created Link entity.
            context: Request context containing client IP, user agent, request ID, etc.
            **kwargs: Additional context (e.g., batch_id).
        """

        # Health check may pass link=None – do nothing in that case
        if link is None:
            return

        data = {
            "url_hash": link.url_hash.value,
            "short_code": link.short_code.value,
            "original_url": mask_url(link.original_url.value),
            "remote_addr": context.remote_addr,
            "user_agent": context.user_agent,
            "request_id": context.request_id,
            "timestamp": link.created_at.isoformat(),
            "event_type": "URL_CREATED",
            **kwargs,
        }
        self._log("Url created", **data)
    
    def log_url_accessed(self, link: Link, context: RequestContext, **kwargs,) -> None:
        """
        Log a URL access (redirect) event.

        Args:
            link: The Link entity being accessed.
            context: Request context containing client IP, user agent, request ID, etc.
            **kwargs: Additional context.
        """

        if link is None:
            return

        data = {
            "short_code": link.short_code.value,
            "original_url": mask_url(link.original_url.value),
            "url_hash": link.url_hash.value,
            "clicks": link.clicks,
            "remote_addr": context.remote_addr,
            "user_agent": context.user_agent,
            "request_id": context.request_id,
            "timestamp": link.last_accessed.isoformat(),
            "event_type": "URL_ACCESSED",
            **kwargs,
        }
        self._log("Url accessed", **data)

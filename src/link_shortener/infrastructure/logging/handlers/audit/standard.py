import logging
from link_shortener.application import AuditLogger, RequestContext
from link_shortener.domain import Link


class StandardAuditLogger(AuditLogger):
    """
    Audit logger using standard logging (fallback when structlog is unavailable).

    Logs events with the same structure but through the standard logging system.
    """

    def __init__(self, name: str = "audit"):
        """Initialize with a standard logger named 'audit'."""
        self._logger = logging.getLogger(name)
    
    def _mask_url(self, url: str) -> str:
        """Mask sensitive parts of the URL for logging."""
        if len(url) > 100:
            return f"{url[:50]}...{url[-20:]}"
        return url
    
    def _log(self, level: str, event: str, **kwargs):
        """Internal method to log with extra data."""
        extra_str = f" - {kwargs}" if kwargs else ""
        getattr(self._logger, level)(f"{event}{extra_str}")
    
    def log_url_created(self, link: Link, context: RequestContext, **kwargs) -> None:
        """Log a URL creation event."""

        # Health check may pass link=None – do nothing in that case
        if link is None:
            return

        self._log("info", "url_created",
                  url_hash=link.url_hash.value,
                  short_code=link.short_code.value,
                  original_url=self._mask_url(link.original_url.value),
                  remote_addr=context.remote_addr,
                  user_agent=context.user_agent,
                  request_id=context.request_id,
                  timestamp=link.created_at.isoformat(),
                  event_type="URL_CREATED",
                  **kwargs)
    
    def log_url_accessed(self, link: Link, context: RequestContext, **kwargs,) -> None:
        """Log a URL access (redirect) event."""

        if link is None:
            return

        self._log("info", "url_accessed",
                  short_code=link.short_code.value,
                  original_url=self._mask_url(link.original_url.value),
                  url_hash=link.url_hash.value,
                  clicks=link.clicks,
                  remote_addr=context.remote_addr,
                  user_agent=context.user_agent,
                  request_id=context.request_id,
                  timestamp=link.created_at.isoformat(),
                  event_type="URL_ACCESSED",
                  **kwargs)

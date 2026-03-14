from datetime import datetime

from link_shortener.application.context import RequestContext
import structlog

from link_shortener.application import AuditLogger
from link_shortener.domain import Link


class StructlogAuditLogger(AuditLogger):
    """
    Audit logger implementation using structlog.

    Logs significant events (URL creation, URL access) to a dedicated audit log.
    Sensitive data (original URL) is masked to prevent leakage.
    """

    def __init__(self):
        """
        Initialize with a structlog logger named 'audit'.
        """
        self._logger = structlog.get_logger("audit")

    def log_url_created(self, link: Link, context: RequestContext, **kwargs) -> None:
        """
        Log a URL creation event.

        Args:
            link: The newly created Link entity.
            context: Request context containing client IP, user agent, request ID, etc.
            **kwargs: Additional context (e.g., batch_id).
        """

        if link is None:
            return

        self._logger.info(
            "url_created",
            url_hash=link.url_hash.value,
            short_code=link.short_code.value,
            original_url=self._mask_url(link.original_url.value),
            is_new=True,
            remote_addr=context.remote_addr,
            user_agent=context.user_agent,
            request_id=context.request_id,
            timestamp=link.created_at.isoformat(),
            event_type="URL_CREATED",
            **kwargs,
        )

    def log_url_accessed(self, link: Link, context: RequestContext, **kwargs) -> None:
        """
        Log a URL access (redirect) event.

        Args:
            link: The Link entity being accessed.
            context: Request context containing client IP, user agent, request ID, etc.
            **kwargs: Additional context.
        """

        if link is None:
            return

        self._logger.info(
            "url_accessed",
            short_code=link.short_code.value,
            original_url=self._mask_url(link.original_url.value),
            url_hash=link.url_hash.value,
            clicks=link.clicks,
            remote_addr=context.remote_addr,
            user_agent=context.user_agent,
            request_id=context.request_id,
            timestamp=datetime.now().isoformat(),
            event_type="URL_ACCESSED",
            **kwargs,
        )

    def _mask_url(self, url: str) -> str:
        """
        Mask sensitive parts of the URL for logging.

        If URL is longer than 100 characters, truncate to first 50 and last 20.
        Otherwise, return as is.
        """

        if len(url) > 100:
            return f"{url[:50]}...{url[-20:]}"
        return url

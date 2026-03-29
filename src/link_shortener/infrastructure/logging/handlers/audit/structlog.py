from datetime import datetime

from link_shortener.infrastructure.logging.utils import mask_url
import structlog

from link_shortener.application import AuditLogger, RequestContext
from link_shortener.domain import Link


class StructlogAuditLogger(AuditLogger):
    """
    Audit logger implementation using structlog.

    This logger uses the structured logging library `structlog` to emit audit
    events with rich, machine‑readable context. It is the preferred implementation
    when structlog is available and configured.
    """

    def __init__(self):
        """
        Initialize the audit logger with a structlog logger named "audit".
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
            original_url=mask_url(link.original_url.value),
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
            original_url=mask_url(link.original_url.value),
            url_hash=link.url_hash.value,
            clicks=link.clicks,
            remote_addr=context.remote_addr,
            user_agent=context.user_agent,
            request_id=context.request_id,
            timestamp=datetime.now().isoformat(),
            event_type="URL_ACCESSED",
            **kwargs,
        )

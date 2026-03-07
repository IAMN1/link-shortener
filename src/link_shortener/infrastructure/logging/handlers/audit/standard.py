from datetime import datetime
import logging
from typing import Optional
from link_shortener.application import AuditLogger
from link_shortener.domain import Link


class StandardAuditLogger(AuditLogger):
    """
    Audit logger using standard logging (fallback when structlog is unavailable).
    Logs events with the same structure but through the standard logging system.
    """

    def __init__(self, name: str = "audit"):
        self._logger = logging.getLogger(name)

        # Ensure there is at least a NullHandler to avoid "No Handlers" warning
        if not self._logger.handlers:
            self._logger.addHandler(logging.NullHandler())
    
    def _mask_url(self, url: str) -> str:
        """"""
        if len(url) > 100:
            return f"{url[:50]}...{url[-20:]}"
        return url
    
    def log_url_created(
        self, link: Link, user_ip: Optional[str] = None, user_agent: Optional[str] = None, **kwargs
    ) -> None:
        """"""

        # Health check may pass link=None – do nothing in that case
        if link is None:
            return

        extra = {
            "url_hash": link.url_hash.value,
            "short_code": link.short_code.value,
            "original_url": self._mask_url(link.original_url.value),
            "user_ip": user_ip,
            "user_agent": user_agent,
            "timestamp": link.created_at.isoformat(),
            "event_type": "URL_CREATED",
            **kwargs,
        }
        self._logger.info("url_created", extra=extra)
    
    def log_url_accessed(
        self, link: Link, user_ip: Optional[str] = None, user_agent: Optional[str] = None, **kwargs,
    ) -> None:
        """"""

        if link is None:
            return

        extra = {
                        "short_code": link.short_code.value,
            "original_url": self._mask_url(link.original_url.value),
            "clicks": link.clicks,
            "user_ip": user_ip,
            "user_agent": user_agent,
            "timestamp": datetime.now().isoformat(),
            "event_type": "URL_ACCESSED",
            **kwargs,
        }
        self._logger.info("url_accessed", extra=extra)
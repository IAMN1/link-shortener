from datetime import datetime
from typing import Optional

import structlog

from link_shortener.application import AuditLogger
from link_shortener.domain import Link


class StructlogAuditLogger(AuditLogger):
    """Реализация аудита логов"""
    def __init__(self):
        self._logger = structlog.get_logger("audit")

    def log_url_created(
        self, link: Link, user_ip: Optional[str] = None, **kwargs
    ) -> None:
        self._logger.info(
            "url_created",
            url_hash=link.url_hash.value,
            short_code=link.short_code.value,
            original_url=self._mask_url(link.original_url.value),
            is_new=True,
            user_ip=user_ip,
            timestamp=link.created_at.isoformat(),
            event_type="URL_CREATED",
        )

    def log_url_accessed(
        self,
        link: Link,
        user_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        **kwargs,
    ) -> None:
        self._logger.info(
            "url_accessed",
            short_code=link.short_code.value,
            original_url=self._mask_url(link.original_url.value),
            clicks=link.clicks,
            user_ip=user_ip,
            user_agent=user_agent,
            timestamp=datetime.now().isoformat(),
            event_type="URL_ACCESSED",
        )

    def _mask_url(self, url: str) -> str:
        """Маскировака чувствительных данных ссылки для логов"""
        if len(url) > 100:
            return f"{url[:50]}...{url[-20:]}"
        return url

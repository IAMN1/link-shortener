from typing import Optional
from link_shortener.application import AuditLogger
from link_shortener.domain import Link


class NullAuditLogger(AuditLogger):
    """
    Null-object audit logger that discards all audit events.
    """

    def log_url_created(
        self, link: Link, user_ip: Optional[str] = None, **kwargs
    ) -> None:
        pass

    def log_url_accessed(
        self, link: Link, user_ip: Optional[str] = None, user_agent: Optional[str] = None, **kwargs
    ) -> None:
        pass
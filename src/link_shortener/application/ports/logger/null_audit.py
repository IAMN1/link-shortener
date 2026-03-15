from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.domain import Link


class NullAuditLogger(AuditLogger):
    """
    Null-object implementation of AuditLogger.

    All audit events are silently discarded.
    Used when audit logging is disabled.
    """

    def log_url_created(self, link: Link, context: RequestContext, **kwargs) -> None:
        """No-op: do nothing."""
        pass

    def log_url_accessed(self, link: Link, context: RequestContext, **kwargs) -> None:
        """No-op: do nothing."""
        pass
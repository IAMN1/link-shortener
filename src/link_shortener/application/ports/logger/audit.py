from abc import ABC, abstractmethod

from link_shortener.application.context import RequestContext
from link_shortener.domain import Link


class AuditLogger(ABC):
    """
    Interface for audit logging of significant events in the application.

    Audit logs are used for security, compliance, and monitoring purposes.
    All methods receive a RequestContext object containing metadata about
    the current request (IP, user agent, request ID, etc.).
    """

    @abstractmethod
    def log_url_created(self, link: Link, context: RequestContext, **kwargs) -> None:
        """
        Log a URL creation event.

        Args:
            link: The newly created Link entity.
            context: Request context containing client IP, user agent, request ID, etc.
            **kwargs: Additional context (e.g., batch_id for bulk operations).
        """
        pass

    @abstractmethod
    def log_url_accessed(self, link: Link, context: RequestContext, **kwargs) -> None:
        """
        Log a URL access (redirect) event.

        Args:
            link: The Link entity being accessed.
            context: Request context containing client IP, user agent, request ID, etc.
            **kwargs: Additional context.
        """
        pass

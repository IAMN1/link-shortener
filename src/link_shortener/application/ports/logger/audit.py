from abc import ABC, abstractmethod
from typing import Optional

from link_shortener.domain import Link


class AuditLogger(ABC):
    """
    Interface for audit logging of significant events in the application.

    Audit logs are used for security, compliance, and monitoring purposes.
    """

    @abstractmethod
    def log_url_created(
        self, link: Link, user_ip: Optional[str] = None, user_agent: Optional[str] = None, **kwargs
    ) -> None:
        """
        Log a URL creation event.

        Args:
            link: The newly created Link entity.
            user_ip: IP address of the user who created the link. Optional.
            user_agent: User-Agent string of the client. Optional.
            **kwargs: Additional context (e.g., batch_id for bulk operations).
        """
        pass

    @abstractmethod
    def log_url_accessed(
        self,
        link: Link,
        user_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        **kwargs,
    ) -> None:
        """
        Log a URL access (redirect) event.

        Args:
            link: The Link entity being accessed.
            user_ip: IP address of the user. Optional.
            user_agent: User-Agent string. Optional.
            **kwargs: Additional context.
        """
        pass

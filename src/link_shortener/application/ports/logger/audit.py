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
            link (Link): The newly created Link entity.
            user_ip (Optional[str], optional): IP address of the user 
                who created the link. Defaults to None.
            user_agent (Optional[str], optional): User-Agent string of the client. 
                Defaults to None.
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
            link (Link): The Link entity being accessed.
            user_ip (Optional[str], optional): IP address of the user. 
                Defaults to None.
            user_agent (Optional[str], optional): User-Agent string. 
                Defaults to None.
            **kwargs: Additional context.
        """
        pass

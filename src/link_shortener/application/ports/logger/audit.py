from abc import ABC, abstractmethod
from typing import Optional

from link_shortener.domain import Link


class AuditLogger(ABC):
    """Интерфейс аудита логов"""

    @abstractmethod
    def log_url_created(
        self, link: Link, user_ip: Optional[str] = None, user_agent: Optional[str] = None, **kwargs
    ) -> None:
        pass

    @abstractmethod
    def log_url_accessed(
        self,
        link: Link,
        user_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        **kwargs,
    ) -> None:
        pass

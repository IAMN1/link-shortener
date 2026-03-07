from typing import List, Optional, Tuple
from link_shortener.application import AuditLogger
from link_shortener.domain import Link
from link_shortener.infrastructure.failover.base import FailoverService


class FailoverAuditLogger(AuditLogger):
    """
    Audit logger that delegates to a FailoverService managing multiple underlying
    audit loggers. Includes background health checks.
    """

    def __init__(
        self, loggers: List[Tuple[AuditLogger, str]], check_interval: float = 30.0):
        """
        Args:
            loggers: List of (audit_logger_instance, logger_name) in priority order.
            check_interval: Seconds between background health checks.
        """

        def _health_check(audit: AuditLogger) -> bool:
            try:
                audit.log_url_created(None)  # link=None is ignored in implementations
                return True
            except Exception:
                return False

        self._service = FailoverService[AuditLogger](
            services=loggers,
            check_interval=check_interval,
            health_checker=_health_check,
        )
    
    def get_current_logger_name(self) -> str:
        return self._service.get_current_serivice_name()

    def log_url_created(
        self, link: Link, user_ip: Optional[str] = None, user_agent: Optional[str] = None, **kwargs
    ) -> None:
        self._service.execute('log_url_created', link, user_ip, user_agent, **kwargs)

    def log_url_accessed(
        self, link: Link, user_ip: Optional[str] = None, user_agent: Optional[str] = None, **kwargs,
    ) -> None:
        self._service.execute('log_url_accessed', link, user_ip, user_agent, **kwargs)
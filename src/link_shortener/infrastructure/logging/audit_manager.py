import sys
from typing import List, Optional, Tuple

from link_shortener.application import AuditLogger, NullAuditLogger
from link_shortener.infrastructure.failover.base import FailoverService
from link_shortener.infrastructure.logging.handlers.audit.standard import StandardAuditLogger
from link_shortener.infrastructure.logging.handlers.audit.structlog import StructlogAuditLogger


class AuditManager:
    """
    Manages audit logger instances with failover support.

    Lifecycle is controlled by the DI container.
    """

    def __init__(self, audit_type: str,  failover_check_interval: float = 30.0):
        """
        Initialize the audit manager.

        Args:
            audit_type: Type of audit logger ('auto', 'structlog', 'standard', 'null')
            failover_check_interval: Seconds between background health checks
        """
        self._failover_check_interval = failover_check_interval
        self._failover_service: Optional[FailoverService] = None
        self._active_audit_logger: Optional[AuditLogger] = None
        self._init_failover_service(audit_type)

    def _init_failover_service(self, audit_type: str):
        """Build the ordered list of audit logger implementations."""

        if audit_type == "auto":
            order = ["structlog", "standard"]
        elif audit_type == "structlog":
            order = ["structlog", "standard"]
        elif audit_type == "standard":
            order = ["standard", "structlog"]
        elif audit_type == "null":
            order = ["null"]
        else:
            order = ["structlog", "standard"]

        audit_loggers: List[Tuple[AuditLogger, str]] = []

        for type_ in order:
            if type_ == "structlog":

                try:
                    struct_audit = StructlogAuditLogger()
                    audit_loggers.append((struct_audit, "structlog_audit"))
                except Exception as e:
                    print(
                        f"WARNING: Failed to initialize StructlogAuditLogger: {e}",
                        file=sys.stderr
                    )
            
            elif type_ == "standard":

                try:
                    std_audit = StandardAuditLogger()
                    audit_loggers.append((std_audit, "standard_audit"))
                except Exception as e:
                    print(
                        f"WARNING: Failed to initialize StandardAuditLogger: {e}",
                        file=sys.stderr
                    )
            
            elif type_ == "null":
                audit_loggers.append((NullAuditLogger(), "null_audit"))
        
        if not audit_loggers:
            audit_loggers.append((NullAuditLogger(), "null_audit"))

        if len(audit_loggers) == 1:  # only NullAuditLogger
            self._failover_service = None
            self._active_audit_logger = audit_loggers[0][0]
        else:
            # Define health check function
            def health_check(audit: AuditLogger) -> bool:
                try:
                    # We need a safe method that doesn't require a link
                    audit.log_url_created(None)  # link=None is ignored in implementations
                    return True
                except Exception:
                    return False

            self._failover_service = FailoverService(
                services=audit_loggers,
                check_interval=self._failover_check_interval,
                health_checker=health_check,
            )

    def get_audit_logger(self) -> AuditLogger:
        """
        Return the audit logger (may be a failover proxy).
        """
        if self._failover_service is None:
            return self._active_audit_logger
        return FailoverAuditLoggerProxy(self._failover_service)

    def shutdown(self):
        """Stop the background failover checker."""
        if self._failover_service:
            self._failover_service.shutdown()


class FailoverAuditLoggerProxy(AuditLogger):
    """
    Proxy that forwards audit calls to the FailoverService.
    """

    def __init__(self, service: FailoverService):
        self._service = service

    def log_url_created(self, link, user_ip=None, user_agent=None, **kwargs):
        self._service.execute("log_url_created", link, user_ip, user_agent, **kwargs)

    def log_url_accessed(self, link, user_ip=None, user_agent=None, **kwargs):
        self._service.execute("log_url_accessed", link, user_ip, user_agent, **kwargs)

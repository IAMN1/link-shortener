import threading
from typing import List, Optional, Tuple

from link_shortener.application import AuditLogger, NullAuditLogger
from link_shortener.infrastructure.failover.base import FailoverService
from link_shortener.infrastructure.logging.handlers.audit.standard import StandardAuditLogger
from link_shortener.infrastructure.logging.handlers.audit.structlog import StructlogAuditLogger


class AuditManager:
    """
    Singleton manager for failover audit logger service.
    Provides a single FailoverService for audit loggers and returns a shared proxy.
    """

    _instance = None
    _lock = threading.Lock()
    _failover_service: Optional[FailoverService] = None
    _audit_logger: Optional[AuditLogger] = None

    def __new__(cls, failover_check_interval: float = 30.0):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self, failover_check_interval: float = 30.0):
        if self._initialized:
            return
        self._initialized = True
        self._failover_check_interval = failover_check_interval
        self._init_failover_service()

    def _init_failover_service(self):
        """Create the list of audit logger implementations."""
        audit_loggers: List[Tuple[AuditLogger, str]] = []

        # 1. StructlogAuditLogger (highest priority)
        try:
            struct_audit = StructlogAuditLogger()
            audit_loggers.append((struct_audit, "structlog_audit"))
        except Exception as e:
            print(f"WARNING: Failed to initialize StructlogAuditLogger: {e}")

        # 2. StandardAuditLogger
        try:
            std_audit = StandardAuditLogger()
            audit_loggers.append((std_audit, "standard_audit"))
        except Exception as e:
            print(f"WARNING: Failed to initialize StandardAuditLogger: {e}")

        # 3. NullAuditLogger (always available)
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
        Return the audit logger proxy.
        """
        if self._audit_logger is None:
            if self._failover_service is None:
                self._audit_logger = self._active_audit_logger
            else:
                self._audit_logger = FailoverAuditLoggerProxy(self._failover_service)
        return self._audit_logger


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
import sys
from typing import List, Optional, Tuple

from link_shortener.application import AuditLogger
from link_shortener.infrastructure.failover.failover_service import FailoverService
from link_shortener.infrastructure.logging.handlers.audit.null_audit import NullAuditLogger
from link_shortener.infrastructure.logging.handlers.audit.standard import StandardAuditLogger
from link_shortener.infrastructure.logging.handlers.audit.structlog import StructlogAuditLogger


class AuditManager:
    """
    Manages audit logger instances with optional failover support.

    Based on the configured `audit_type`, this class creates a list of
    available audit logger implementations (structlog, standard, null)
    in priority order. If multiple implementations are available, a
    `FailoverService` is used to automatically switch to a fallback
    when the primary fails.

    Lifecycle is controlled by the DI container.
    """

    def __init__(self, audit_type: str,  failover_check_interval: float = 30.0):
        """
        Initialize the audit manager.

        Args:
            audit_type: Type of audit logger: 'auto', 'structlog', 'standard', 'null'.
            failover_check_interval: Seconds between background health checks
                (ignored if only one implementation is available).
        """
        self._failover_check_interval = failover_check_interval
        self._failover_service: Optional[FailoverService] = None
        self._active_audit_logger: Optional[AuditLogger] = None
        self._init_failover_service(audit_type)

    def _init_failover_service(self, audit_type: str):
        """
        Build the ordered list of audit logger implementations.
        """

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
                    audit.log_url_created("health_check", "http://health")
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
        Return the audit logger instance.

        If failover is configured, returns a `FailoverAuditLoggerProxy`
        that wraps the `FailoverService`. Otherwise returns the single
        active logger.

        Returns:
            AuditLogger instance.
        """
        if self._failover_service is None:
            return self._active_audit_logger
        return FailoverAuditLoggerProxy(self._failover_service)

    def shutdown(self):
        """Stop the background failover checker if it exists."""
        if self._failover_service:
            self._failover_service.shutdown()


class FailoverAuditLoggerProxy(AuditLogger):
    """
    Proxy that forwards audit calls to the `FailoverService`.

    It maintains its own `_bound_fields` to support `bind` operations.
    When a log method is called, it merges bound fields with the arguments
    and delegates to the service.
    """

    def __init__(self, service: FailoverService, bound_fields: dict = None):
        """
        nitialize the proxy.

        Args:
            service: The `FailoverService` that holds the actual loggers.
            bound_fields: Initial bound fields (e.g., request context).
        """
        self._service = service
        self._bound_fields = bound_fields or {}

    def bind(self, **kwargs) -> "FailoverAuditLoggerProxy":
        """
        Return a new proxy with additional bound fields.

        Args:
            **kwargs: Fields to bind.

        Returns:
            A new `FailoverAuditLoggerProxy` instance with merged bound fields.
        """
        return FailoverAuditLoggerProxy(self._service, {**self._bound_fields, **kwargs})

    def log_url_created(self, short_code: str, original_url: str, **kwargs) -> None:
        """
        Forward the URL creation event to the active audit logger via failover.

        Args:
            short_code: The generated short code.
            original_url: The original long URL.
            **kwargs: Additional context.
        """
        all_kwargs = {**self._bound_fields, **kwargs}
        self._service.execute("log_url_created", short_code, original_url, **all_kwargs)

    def log_url_accessed(self, short_code: str, original_url: str, **kwargs) -> None:
        """
        Forward the URL access event to the active audit logger via failover.

        Args:
            short_code: The short code that was accessed.
            original_url: The original URL to which the user was redirected.
            **kwargs: Additional context.
        """
        all_kwargs = {**self._bound_fields, **kwargs}
        self._service.execute("log_url_accessed", short_code, original_url, **all_kwargs)

    def log_url_deleted(self, short_code: str, original_url: str, **kwargs) -> None:
        """
        Forward the URL deletion event to the active audit logger via failover.

        Args:
            short_code: The short code of the deleted link.
            original_url: The original long URL that was shortened.
            **kwargs: Additional context.
        """
        all_kwargs = {**self._bound_fields, **kwargs}
        self._service.execute("log_url_deleted", short_code, original_url, **all_kwargs)

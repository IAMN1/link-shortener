from link_shortener.application import AuditLogger
from link_shortener.infrastructure.logging.managers.audit_manager import AuditManager


class AuditComponent:
    """
    Manages the lifecycle of the audit logger.

    The effective audit type is determined by ``audit_enabled``: if False,
    ``"null"`` is forced irrespective of the configured type.
    """
    def __init__(self, audit_enabled: bool, audit_type: str, failover_check_interval: float):
        """
        Args:
            audit_enabled: Global flag; if False, a null logger is used.
            audit_type: Desired logger type (``"auto"``, ``"structlog"``,
                ``"standard"``, ``"null"``).
            failover_check_interval: Seconds between health checks for
                failover.
        """
        self.audit_enabled = audit_enabled
        self.audit_type = audit_type
        self.failover_check_interval = failover_check_interval
        self._manager = None

    def get_audit_logger(self) -> AuditLogger:
        """
        Obtain the configured audit logger.

        On first call, an ``AuditManager`` is created. The effective
        ``audit_type`` is forced to ``"null"`` when auditing is disabled.

        Returns:
            An ``AuditLogger`` instance (possibly a failover proxy).
        """
        if not self._manager:
            effective_type = "null" if not self.audit_enabled else self.audit_type
            self._manager = AuditManager(
                audit_type=effective_type,
                failover_check_interval=self.failover_check_interval
            )
        return self._manager.get_audit_logger()

    def shutdown(self):
        """Gracefully stop background failover checks."""
        if self._manager:
            self._manager.shutdown()

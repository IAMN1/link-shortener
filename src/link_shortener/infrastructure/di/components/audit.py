from typing import Optional

from link_shortener.application import AuditLogger
from link_shortener.application.ports.logging_status import (
    ChainStatus, NOT_STARTED,
)
from link_shortener.infrastructure.failover.failover_service import CheckOutcome
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
        # Annotated Optional rather than inferred from this assignment: the
        # attribute holds None until the first call builds it, and a checker
        # told otherwise reports both the assignment and the return as errors.
        self._manager: Optional[AuditManager] = None

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

    def chain_status(self) -> ChainStatus:
        """
        Report the chain without building it.

        The audit half of what ``LoggerComponent.chain_status`` reports,
        and here for the same reason: the reader that publishes it was
        reaching into ``self._manager``, and this component offered no way
        to ask.

        Returns:
            The chain's state -- or ``NOT_STARTED``, zeroes and a check
            that has not run, where no manager has been built.
        """
        if self._manager is None:
            return ChainStatus(
                active=NOT_STARTED,
                dropped_calls=0,
                failed_checks=0,
                lost_log_lines=0,
                last_check=CheckOutcome.NOT_RUN.value,
            )

        dropped, failed, lost = self._manager.counters()
        return ChainStatus(
            active=self._manager.active_name(),
            dropped_calls=dropped,
            failed_checks=failed,
            lost_log_lines=lost,
            last_check=self._manager.last_check(),
        )

    def shutdown(self):
        """Gracefully stop background failover checks."""
        if self._manager:
            self._manager.shutdown()

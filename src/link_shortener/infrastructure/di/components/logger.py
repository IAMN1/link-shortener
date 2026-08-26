from typing import Optional

from link_shortener.application import Logger
from link_shortener.application.ports.logging_status import (
    ChainStatus, NOT_STARTED,
)
from link_shortener.infrastructure.failover.failover_service import CheckOutcome
from link_shortener.infrastructure.logging.managers.logger_manager import LoggerManager


class LoggerComponent:
    """
    Provides loggers for any module in the application.

    The effective logger type is forced to ``"null"`` when logging is
    globally disabled. A ``LoggerManager`` handles the creation and
    failover of the underlying logger implementations.
    """
    def __init__(self, logging_enabled: bool, logger_type: str, failover_check_interval: float):
        """
        Args:
            logging_enabled: Global flag; if False, a null logger is used.
            logger_type: Desired logger type (``"auto"``, ``"structlog"``,
                ``"standard"``, ``"null"``).
            failover_check_interval: Seconds between health checks for
                failover.
        """
        self.logging_enabled = logging_enabled
        self.logger_type = logger_type
        self.failover_check_interval = failover_check_interval
        # Annotated Optional rather than inferred from this assignment: the
        # attribute holds None until the first call builds it, and a checker
        # told otherwise reports both the assignment and the return as errors.
        self._manager: Optional[LoggerManager] = None

    def get_logger(self, module_name: str) -> Logger:
        """
        Return a logger for the given module, possibly a failover proxy.

        The logger's context will include the module name as a bound field.

        Args:
            module_name: Typically ``__name__`` of the calling module.

        Returns:
            A ``Logger`` instance.
        """
        if not self._manager:
            effective_type = "null" if not self.logging_enabled else self.logger_type
            self._manager = LoggerManager(
                logger_type=effective_type,
                failover_check_interval=self.failover_check_interval
            )
        return self._manager.get_logger(module_name)

    def chain_status(self) -> ChainStatus:
        """
        Report the chain without building it.

        Here rather than at the reader that publishes it: that reader took
        ``self._manager`` off this object directly -- a private attribute
        of somebody else's -- and worked out from it both the name and the
        counters, which is this component's own business and was already
        half-written here. Renaming the attribute would have broken
        ``/api/v1/admin/health`` with an ``AttributeError`` and nothing
        would have said so until a request arrived.

        Asking must not be what starts the chain: a manager is built on
        the first logger somebody wants, and a health check is not that.

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
            active=self._manager.get_active_logger_name(),
            dropped_calls=dropped,
            failed_checks=failed,
            lost_log_lines=lost,
            last_check=self._manager.last_check(),
        )

    def get_active_logger_name(self) -> str:
        """
        Return the name of the currently active logger implementation.

        Useful for debugging and startup diagnostics.

        Returns:
            One of ``"structlog"``, ``"standard"``, ``"null"``, or
            ``NOT_STARTED``.
        """
        return self.chain_status().active

    def shutdown(self):
        """Stop background failover checks and release resources."""
        if self._manager:
            self._manager.shutdown()

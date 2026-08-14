from typing import Optional
from link_shortener.application import Logger
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

    def get_active_logger_name(self) -> str:
        """
        Return the name of the currently active logger implementation.

        Useful for debugging and startup diagnostics.

        Returns:
            One of ``"structlog"``, ``"standard"``, ``"null"``, or
            ``"unknown"``.
        """
        if self._manager:
            return self._manager.get_active_logger_name()
        return "unknown"

    def shutdown(self):
        """Stop background failover checks and release resources."""
        if self._manager:
            self._manager.shutdown()

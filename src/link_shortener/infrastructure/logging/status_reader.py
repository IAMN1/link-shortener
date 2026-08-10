from link_shortener.application.ports.logging_status import (
    LoggingStatus, LoggingStatusPort,
)


class ComponentLoggingStatus(LoggingStatusPort):
    """
    Reads the two logging components without building anything.

    A manager is created lazily, on the first logger anyone asks for, so a
    component that has not been used yet has nothing to report -- and
    asking it here must not be what brings the chain into existence.
    ``"not started"`` says that plainly in ``*_active``. The counters do
    come back as zeroes there -- there is nothing else to report about a
    chain that was never built -- so it is the name beside them that tells
    "nothing lost" from "nobody looked".
    """

    NOT_STARTED = "not started"
    """Answer for a chain nothing has asked for yet."""

    def __init__(self, logger_component, audit_component):
        """
        Args:
            logger_component: The DI component holding ``LoggerManager``.
            audit_component: The DI component holding ``AuditManager``.
        """
        self._logger_component = logger_component
        self._audit_component = audit_component

    def read(self) -> LoggingStatus:
        """
        Take the current state of both chains.

        Returns:
            The counters and the active implementations.
        """
        logger_manager = self._logger_component._manager
        audit_manager = self._audit_component._manager

        logger_dropped, logger_failed, logger_lost = (
            logger_manager.counters() if logger_manager else (0, 0, 0)
        )
        audit_dropped, audit_failed, audit_lost = (
            audit_manager.counters() if audit_manager else (0, 0, 0)
        )

        return LoggingStatus(
            logger_active=(
                logger_manager.get_active_logger_name()
                if logger_manager else self.NOT_STARTED
            ),
            logger_dropped_calls=logger_dropped,
            logger_failed_checks=logger_failed,
            logger_lost_log_lines=logger_lost,
            audit_active=(
                audit_manager.active_name()
                if audit_manager else self.NOT_STARTED
            ),
            audit_dropped_calls=audit_dropped,
            audit_failed_checks=audit_failed,
            audit_lost_log_lines=audit_lost,
        )

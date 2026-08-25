import os
from typing import Protocol, Tuple

from link_shortener.application.ports.logging_status import (
    LoggingStatus, LoggingStatusPort,
)


class LoggingChain(Protocol):
    """A component that can report its chain without building it."""

    def chain_status(self) -> Tuple[str, int, int, int]:
        """
        Return the active implementation and the three counters.

        Returns:
            Active implementation, dropped calls, failed check rounds and
            lost failover log lines.
        """
        ...


class ComponentLoggingStatus(LoggingStatusPort):
    """
    Reads the two logging components without building anything.

    Each component answers for its own chain. This class used to take
    ``_manager`` off both of them -- a private attribute of somebody
    else's object -- and work the name and the counters out from it,
    which is how a rename in either component would have turned
    ``/api/v1/admin/health`` into an ``AttributeError`` with nothing to
    warn anyone first. What "nothing has been built yet" is called lives
    with the port now, beside the field it goes in.
    """

    def __init__(self, logger_component: LoggingChain, audit_component: LoggingChain):
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
        logger_active, logger_dropped, logger_failed, logger_lost = (
            self._logger_component.chain_status()
        )
        audit_active, audit_dropped, audit_failed, audit_lost = (
            self._audit_component.chain_status()
        )

        return LoggingStatus(
            # Read here rather than passed in, because it is what makes
            # the counters readable: they live in the memory of this
            # process and nowhere else.
            worker=os.getpid(),
            logger_active=logger_active,
            logger_dropped_calls=logger_dropped,
            logger_failed_checks=logger_failed,
            logger_lost_log_lines=logger_lost,
            audit_active=audit_active,
            audit_dropped_calls=audit_dropped,
            audit_failed_checks=audit_failed,
            audit_lost_log_lines=audit_lost,
        )

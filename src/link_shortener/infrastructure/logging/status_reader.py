import os
from typing import Protocol

from link_shortener.application.ports.logging_status import (
    ChainStatus, LoggingStatus, LoggingStatusPort,
)
from link_shortener.infrastructure.logging.bootstrap import (
    journals_unavailable, journals_written,
)


class LoggingChain(Protocol):
    """A component that can report its chain without building it."""

    def chain_status(self) -> ChainStatus:
        """
        Return what the chain has been doing, without starting it.

        Returns:
            The active implementation, the three counters and what the
            last background round found.
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
        return LoggingStatus(
            # Read here rather than passed in, because it is what makes
            # the counters readable: they live in the memory of this
            # process and nowhere else.
            worker=os.getpid(),
            # The same reason, one step earlier in the same process: which
            # journals this worker could open is settled while it starts,
            # by `setup_logging`, and is remembered where it was found.
            # Both halves, because neither is readable alone: no failures
            # is the answer for a worker writing three journals and for
            # one writing none.
            journals_written=journals_written(),
            journals_unavailable=journals_unavailable(),
            # Each component answers for its own chain, and answers with
            # one object: this used to unpack two tuples of four into
            # eight names on the way into a flat status, where a pair
            # swapped between the chains read as a plausible answer.
            logger=self._logger_component.chain_status(),
            audit=self._audit_component.chain_status(),
        )

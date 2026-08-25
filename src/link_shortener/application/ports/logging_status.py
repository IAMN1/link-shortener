from abc import ABC, abstractmethod
from dataclasses import dataclass


NOT_STARTED = "not started"
"""What ``*_active`` says about a chain nothing has asked for yet.

A manager is built lazily, on the first logger a caller wants, so a
component nothing has used has no implementation to name -- and being
asked here must not be what brings the chain into existence. The counters
come back as zeroes beside it, there being nothing else to report about a
chain that was never built, so it is this name that tells "nothing lost"
from "nobody looked".

One word, because there were two: the DI component answered ``unknown``
and the reader beside it answered ``not started``, about the same chain in
the same state.
"""


@dataclass(frozen=True)
class LoggingStatus:
    """
    What the logging and audit chains have been doing.

    Exists because none of it was reachable. The counters were kept and
    read by nothing, the only runtime word about which implementation holds
    the work was one line at startup, and ``/health`` reported the
    database, the cache, the queue and the throttle -- never the log. So
    "auditing stopped being written" looked, from every surface an operator
    has, exactly like "auditing is fine".

    Attributes:
        worker: The process these counters were taken in. They live in
            its memory and nowhere else, and a deployment runs several:
            four gunicorn workers, each with its own chain and its own
            counts. Measured on the running stack after one broken
            journal, twelve requests to ``/api/v1/admin/health`` in one
            state of one service answered ``dropped_calls`` 16, 27, 28
            and 6, by which worker happened to take the request -- and a
            worker that served no traffic during the outage answers zero,
            which is the "everything is fine" this block exists to end.
            Named in the answer so the number is read as one process's,
            because summing them needs a store the chain does not have
            and must not depend on: the cache is a thing that fails.
        logger_active: Implementation currently writing application logs.
        logger_dropped_calls: Calls every implementation refused. A
            call is not a record: one refused ``log.info`` is one
            dropped call, and what it would have written is lost with
            it, but the two are not counted in the same units.
        logger_failed_checks: Background rounds that could not complete.
        logger_lost_log_lines: Lines the failover service wrote about its
            own working that its logger refused. Not records passing
            through the chain -- those are ``logger_dropped_calls`` --
            but the account of what the chain did, missing precisely
            when the chain had something to say.
        audit_active: Implementation currently writing the audit trail.
        audit_dropped_calls: Calls every implementation refused, in the
            same units as ``logger_dropped_calls``.
        audit_failed_checks: Background rounds that could not complete.
        audit_lost_log_lines: The same as ``logger_lost_log_lines``, for
            the audit chain.
    """

    worker: int
    logger_active: str
    logger_dropped_calls: int
    logger_failed_checks: int
    logger_lost_log_lines: int
    audit_active: str
    audit_dropped_calls: int
    audit_failed_checks: int
    audit_lost_log_lines: int


class LoggingStatusPort(ABC):
    """Reads the state of the logging chains without writing to them."""

    @abstractmethod
    def read(self) -> LoggingStatus:
        """
        Take the current state of both chains.

        Returns:
            The counters and the active implementations.
        """
        ...

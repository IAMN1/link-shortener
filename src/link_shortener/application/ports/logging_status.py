from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Tuple


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
class JournalUnavailable:
    """A journal file this process could not open when it started.

    A handler is built by opening its file, so a path that cannot be
    opened -- a directory where a file belongs, a mode the user cannot
    write, a full disk -- used to raise out of the logging bootstrap and
    out of ``create_app`` with it. Measured on the live stack with
    ``application.log`` replaced by a directory: the container sat in
    ``Restarting (1)``, the public ``/health`` answered nothing at all,
    and the only word about why was ``Worker failed to boot`` in the
    gunicorn output. The whole failover exists so that a journal going
    away does not take the service with it, and the service was not
    reaching failover -- it was not reaching a request.

    So a handler that will not open is left out and named here instead.
    Reported rather than merely survived, because a service writing to
    one journal of three looks exactly like a service writing to three
    from every surface an operator has.

    Attributes:
        journal: Which of the three, by the same names ``Journal`` uses,
            so one word means one file across the reader, the health
            answer and the shell.
        reason: What the operating system said, as it said it -- the
            message names both the path and the cause, and an operator
            reading "Is a directory" knows what to do about it in a way
            that "logging degraded" does not tell them.
    """

    journal: str
    reason: str


@dataclass(frozen=True)
class ChainStatus:
    """What one failover chain answers about itself.

    An object rather than the five values in a row: this used to be a
    tuple of four passed hand to hand from the DI component through the
    reader into a flat status of eight fields, where ``logger_`` and
    ``audit_`` prefixes carried the only word about which chain a number
    belonged to. The published answer was never flat -- it has had a
    ``logger`` and an ``audit`` section from the first day -- so the flat
    middle was a shape nothing at either end asked for, and every value
    added to a chain widened a tuple, a protocol, a dataclass and two
    call sites at once.

    Attributes:
        active: Implementation currently doing the work, or
            ``NOT_STARTED`` where the chain has not been built.
        dropped_calls: Calls every implementation refused. A call is not
            a record: one refused ``log.info`` is one dropped call, and
            what it would have written is lost with it, but the two are
            not counted in the same units.
        failed_checks: Background rounds that could not complete.
        lost_log_lines: Lines the failover service wrote about its own
            working that its logger refused. Not records passing through
            the chain -- those are ``dropped_calls`` -- but the account
            of what the chain did, missing precisely when the chain had
            something to say.
        last_check: What the last background round found this chain to
            be. The counters above cannot say it: they count losses, and
            a chain can report itself unwell for as long as nothing is
            asked of it without any of them moving.
    """

    active: str
    dropped_calls: int
    failed_checks: int
    lost_log_lines: int
    last_check: str


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
        logger: The chain writing application logs.
        audit: The chain writing the audit trail.
        journals_written: Journals this process opened when it started.
            About the files, not about the chains: a journal opened at
            start-up and broken an hour later is still named here, and
            what the chain writing it found last is
            ``ChainStatus.last_check``. Measured with ``audit.log``
            replaced by a directory on a running application: this list
            still held all three, and ``audit.last_check`` read
            ``unhealthy``.
            Beside the tuple below because that one alone cannot say it:
            an empty list of failures is the answer both for a process
            writing all three journals and for one writing none, and a
            deployment running ``LOG_TO_FILE=false`` is the second. The
            same trap ``cache_configured`` was added for, in the same
            answer -- "nothing is broken" read as "everything is working"
            over a service with no such thing configured at all.
        journals_unavailable: Journals this process could not open when
            it started, in the order the handlers were built. Empty on a
            healthy deployment, and it is the empty tuple rather than a
            default: a status object that forgets to say which journals
            are missing says instead that none are, and that was the
            state the whole block exists to stop looking like health.
    """

    worker: int
    logger: ChainStatus
    audit: ChainStatus
    journals_written: Tuple[str, ...]
    journals_unavailable: Tuple[JournalUnavailable, ...]


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

"""The audit logger that also counts what it is told.

The journal answers "what happened"; it cannot answer "how many". It is a
file read from its end, and a filtered read of fifty thousand lines --
measured at some 130 ms on this tree -- reaches about an hour and a half of
a busy service. A chart of the last ninety days has to come from somewhere
else, and this is the seam where the same event reaches both.

A wrapper rather than a call at each site that writes: the vocabulary has
twenty events, written from the use cases, the error handler and the CLI,
and a counter invoked beside each `audit.log_*` is a counter that the next
one forgets. Here, every event is counted by construction, and the next one
is counted without a line of proof being needed anywhere -- which is how
`USER_PASSWORD_RESET`, added from a command rather than from a use case,
reached the charts without this file being touched.
"""

from datetime import datetime, timezone

from link_shortener.application.ports.logger.audit import AuditEvent, AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory


COUNTED_ELSEWHERE = frozenset({
    AuditEvent.URL_CREATED,
    AuditEvent.URL_ACCESSED,
    AuditEvent.URL_DELETED,
})
"""Events this logger does not count, because another table already does.

A redirect writes a row to ``link_visits`` through a background task, so
the redirect itself is not made slower; counting it here as well would put
a synchronous insert on the hottest path in the service to reach a number
that table already holds.

Checked against the event rather than left to which method was called. The
link events have methods of their own and would ordinarily arrive through
them -- but ``log_security_event`` takes any member of the vocabulary, and
one call spelled the other way would double-count every redirect against a
figure nobody would think to compare.
"""


class CountingAuditLogger(AuditLogger):
    """
    Records every security event in the database, then logs it as usual.

    Only the security events. The three link events are left alone
    deliberately: a redirect already writes a row to ``link_visits``,
    through a background task so that the redirect itself is not made
    slower, and counting it a second time here would put a synchronous
    insert on the hottest path in the service to reach a number the other
    table already holds.

    Attributes:
        inner: The audit logger this one wraps and delegates to.
        uow_factory: Opens the transaction each count is written in.
        logger: Where a failure to count is reported.
    """

    def __init__(
        self,
        inner: AuditLogger,
        uow_factory: UnitOfWorkFactory,
        logger: Logger,
    ):
        """
        Args:
            inner: The audit logger to delegate to.
            uow_factory: Callable returning a new Unit of Work.
            logger: Application logger, for a failure to count.
        """
        self._inner = inner
        self._uow_factory = uow_factory
        self._logger = logger

    def bind(self, **kwargs) -> "CountingAuditLogger":
        """
        Return a wrapper around the bound inner logger.

        Args:
            **kwargs: Fields to bind.

        Returns:
            A new wrapper; the counting half has no context to bind, since
            it stores an event type and a moment and nothing else.
        """
        return CountingAuditLogger(
            self._inner.bind(**kwargs), self._uow_factory, self._logger
        )

    def log_url_created(self, short_code: str, original_url: str, **kwargs) -> None:
        """Delegate; a link event is not counted here. See the class."""
        self._inner.log_url_created(short_code, original_url, **kwargs)

    def log_url_accessed(self, short_code: str, original_url: str, **kwargs) -> None:
        """Delegate; a link event is not counted here. See the class."""
        self._inner.log_url_accessed(short_code, original_url, **kwargs)

    def log_url_deleted(self, short_code: str, original_url: str, **kwargs) -> None:
        """Delegate; a link event is not counted here. See the class."""
        self._inner.log_url_deleted(short_code, original_url, **kwargs)

    def log_security_event(self, event: AuditEvent, **fields) -> None:
        """
        Count the event, then write it to the journal.

        In that order, and the order is the safe one: the journal is the
        record an incident is reconstructed from, so it must be written
        whatever the database is doing. Counting first and logging after
        means a database failure cannot take the journal line with it --
        the count is lost, the record is not.

        Args:
            event: Which event this is.
            **fields: The event's fields, passed through untouched.
        """
        self._count(event)
        self._inner.log_security_event(event, **fields)

    def _count(self, event: AuditEvent) -> None:
        """
        Add one to the count of this event, in its own transaction.

        Its own, rather than the caller's: this logger is handed to use
        cases that are mid-transaction, and joining theirs would make a
        failed count roll back the work it was recording -- an account
        that was not created because the service could not count it.

        Which is why the callers write their event *after* their own block
        closes. Two transactions at once is two connections out of the pool
        for one administrative action, on a deployment of four sync
        workers, and the second of them exists only to add a row nobody is
        waiting on. Held by
        ``test_a_security_event_is_written_outside_the_transaction``.

        A failure here is swallowed after being logged, for the reason
        the failover machinery swallows its own: the count is a
        statistic, and taking down the request that produced it would
        trade the thing being measured for the measurement.

        Args:
            event: The event to count.
        """
        if event in COUNTED_ELSEWHERE:
            return

        try:
            with self._uow_factory() as uow:
                uow.security_events.record(
                    event_type=event.value,
                    occurred_at=datetime.now(timezone.utc),
                )
                uow.commit()
        except Exception as error:
            self._logger.warning(
                "Security event was not counted",
                event_type=event.value,
                error=str(error),
            )

    def is_healthy(self) -> bool:
        """
        Report the health of the logger underneath.

        The counting half is deliberately not part of the answer: it is a
        statistic, and a service whose audit trail is being written should
        not report itself unwell because a chart is missing a bar.

        Returns:
            Whatever the wrapped logger says.
        """
        return self._inner.is_healthy()

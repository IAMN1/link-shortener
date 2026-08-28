"""The wrapper that counts what the audit journal is told.

The journal cannot answer "how many": it is a file read from its end, and a
filtered read of fifty thousand lines reaches about an hour and a half of a
busy service. So the same event goes to two places, and this is the seam.

Two properties are worth holding, and both are about what the counting must
*not* cost. It must not put a synchronous insert on the redirect path,
which is why the link events are passed through untouched; and it must not
be able to take down the request whose event it was counting, which is why
a failure to count is swallowed after the journal line is written.
"""

from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from link_shortener.application.ports.logger.audit import AuditEvent, AuditLogger
from link_shortener.infrastructure.logging.handlers.audit.counting import (
    CountingAuditLogger,
)


@pytest.fixture
def inner():
    """The audit logger underneath, watched for what reaches it."""
    logger = Mock(spec=AuditLogger)
    logger.bind.return_value = logger
    return logger


@pytest.fixture
def uow():
    """A unit of work whose security event repository is watched."""
    unit = Mock()
    unit.__enter__ = Mock(return_value=unit)
    unit.__exit__ = Mock(return_value=False)
    return unit


@pytest.fixture
def uow_factory(uow):
    """A factory handing out that one unit of work."""

    @contextmanager
    def factory(*args, **kwargs):
        yield uow

    return factory


@pytest.fixture
def counting(inner, uow_factory):
    """The wrapper under test."""
    return CountingAuditLogger(
        inner=inner, uow_factory=uow_factory, logger=Mock()
    )


class TestEverySecurityEventIsCounted:
    """By construction rather than by a call at each site.

    The events are written from use cases all over the application; a
    counter invoked beside each `audit.log_*` is a counter the next event
    added forgets.
    """

    def test_the_event_reaches_the_repository(self, counting, uow):
        counting.log_security_event(AuditEvent.LOGIN_FAILED)

        _, kwargs = uow.security_events.record.call_args
        assert kwargs["event_type"] == "LOGIN_FAILED"

    def test_the_moment_is_recorded_with_it(self, counting, uow):
        """A count with no time in it cannot be a chart."""
        counting.log_security_event(AuditEvent.LOGIN_SUCCEEDED)

        assert uow.security_events.record.call_args[1]["occurred_at"] is not None

    def test_the_transaction_is_committed(self, counting, uow):
        """An uncommitted count is not a count."""
        counting.log_security_event(AuditEvent.USER_CREATED)

        uow.commit.assert_called_once()

    def test_the_named_wrappers_are_counted_too(self, counting, uow):
        """They are concrete on the port and funnel into the one method,
        so the wrapper gains the whole family without naming any of it."""
        counting.log_login_failed("ivanov@example.com", "bad_password")

        assert uow.security_events.record.call_args[1]["event_type"] == "LOGIN_FAILED"

    def test_every_event_in_the_vocabulary_lands(self, counting, uow):
        """A member added to `AuditEvent` is counted without a line of
        proof being needed anywhere."""
        for event in AuditEvent:
            counting.log_security_event(event)

        counted = {
            call.kwargs["event_type"]
            for call in uow.security_events.record.call_args_list
        }
        security = {
            event.value for event in AuditEvent
            if not event.value.startswith("URL_")
        }
        assert counted == security


class TestTheLinkEventsAreNotCounted:
    """A redirect already writes a row to ``link_visits``.

    It does so through a background task, so the redirect itself is not
    made slower. Counting it again here would put a synchronous insert on
    the hottest path in the service to reach a number another table
    already holds.
    """

    @pytest.mark.parametrize(
        "method", ["log_url_created", "log_url_accessed", "log_url_deleted"]
    )
    def test_nothing_is_written(self, counting, uow, inner, method):
        getattr(counting, method)("abc123", "https://example.com/")

        uow.security_events.record.assert_not_called()
        getattr(inner, method).assert_called_once()

    @pytest.mark.parametrize(
        "event",
        [AuditEvent.URL_CREATED, AuditEvent.URL_ACCESSED, AuditEvent.URL_DELETED],
    )
    def test_nor_when_spelled_through_the_general_method(
        self, counting, uow, inner, event
    ):
        """The rule is about the event, not about which method was used.

        `log_security_event` takes any member of the vocabulary, and one
        redirect logged the other way would double-count against a figure
        nobody would think to compare.
        """
        counting.log_security_event(event, short_code="abc123")

        uow.security_events.record.assert_not_called()
        inner.log_security_event.assert_called_once()


class TestTheJournalIsWrittenWhateverTheDatabaseDoes:
    """The journal is what an incident is reconstructed from."""

    def test_a_failed_count_does_not_stop_the_journal_line(self, inner):
        """The count is a statistic; the record is not. Losing the first
        to keep the second is the trade this wrapper exists to make."""
        def broken(*args, **kwargs):
            raise RuntimeError("the database is down")

        counting = CountingAuditLogger(
            inner=inner, uow_factory=broken, logger=Mock()
        )

        counting.log_security_event(AuditEvent.LOGIN_FAILED, reason="bad")

        inner.log_security_event.assert_called_once()

    def test_a_failed_count_is_reported_rather_than_silent(self, inner):
        """Swallowed is not the same as unnoticed: a chart that quietly
        stopped counting is worse than one that is missing."""
        def broken(*args, **kwargs):
            raise RuntimeError("the database is down")

        logger = Mock()
        counting = CountingAuditLogger(
            inner=inner, uow_factory=broken, logger=logger
        )

        counting.log_security_event(AuditEvent.LOGIN_FAILED)

        logger.warning.assert_called_once()

    def test_the_count_is_taken_before_the_line_is_written(
        self, counting, uow, inner
    ):
        """In that order, so that a database failure cannot take the
        journal line with it."""
        order = []
        uow.security_events.record.side_effect = lambda **kw: order.append("count")
        inner.log_security_event.side_effect = lambda *a, **kw: order.append("log")

        counting.log_security_event(AuditEvent.LOGIN_FAILED)

        assert order == ["count", "log"]


class TestItIsStillAnAuditLogger:
    """It stands where one stood, so it answers everything one answers."""

    def test_binding_returns_another_wrapper(self, counting, inner):
        bound = counting.bind(request_id="req-1")

        assert isinstance(bound, CountingAuditLogger)
        inner.bind.assert_called_once_with(request_id="req-1")

    def test_a_bound_wrapper_still_counts(self, counting, uow):
        counting.bind(request_id="req-1").log_security_event(
            AuditEvent.LOGIN_FAILED
        )

        uow.security_events.record.assert_called_once()

    def test_health_is_the_wrapped_logger_s_answer(self, counting, inner):
        """The counting half is deliberately not part of it: a service
        whose audit trail is being written should not report itself unwell
        because a chart is missing a bar."""
        inner.is_healthy.return_value = False
        assert counting.is_healthy() is False

        inner.is_healthy.return_value = True
        assert counting.is_healthy() is True

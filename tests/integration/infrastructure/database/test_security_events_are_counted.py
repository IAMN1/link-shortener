"""
Integration tests for the counting half of the audit journal.

The same reasoning as the visit aggregates next door: bucketing is
arithmetic done by the database, in two dialects that spell it differently,
on values whose timezone SQLite does not keep. Every part of that is a
place where a chart comes out shifted by a bucket, double-counted, or
silently empty while every unit test passes.

The roll-up is checked here too, for a reason of its own: it folds days and
the sweep then deletes the rows behind them, so an error in the order or in
the day boundary is not a wrong number on a page -- it is history that no
longer exists.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete

from link_shortener.infrastructure.database.models.security_event_model import (
    SecurityEventDayModel, SecurityEventModel,
)


NOON = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def uow_factory(app):
    """Unit of Work factory bound to the integration database.

    The table is emptied first. Unlike the visits next door, a security
    event is scoped by nothing -- no link, no owner -- so every test here
    counts every row any other test left behind, and the `app` fixture is
    session-scoped.
    """
    with app.app_context():
        factory = app.container.get_uow_factory()
        with factory() as uow:
            uow._session.execute(delete(SecurityEventModel))
            uow._session.execute(delete(SecurityEventDayModel))
            uow.commit()
        yield factory


def record(uow_factory, event_type, at):
    """
    Store one security event.

    Args:
        uow_factory: Factory for Unit of Work instances.
        event_type: The event's own name.
        at: When it happened, in UTC.
    """
    with uow_factory() as uow:
        uow.security_events.record(event_type=event_type, occurred_at=at)
        uow.commit()


def totals_between(uow_factory, since, until):
    """
    What a span amounted to, by kind, read the way the use case reads it.

    One bucket over the whole span, added up -- there is no second query
    for totals, and that is the point: two queries were free to disagree.

    Args:
        uow_factory: Factory for a unit of work.
        since: Start of the span, inclusive.
        until: End of the span, exclusive.

    Returns:
        Mapping of event type to count.
    """
    with uow_factory(read_only=True) as uow:
        series = uow.security_events.buckets_between(since, until, 1)
    return {event_type: sum(counts) for event_type, counts in series}


class TestCountingASpan:
    """What fell inside a span, by kind."""

    def test_each_kind_is_counted_apart(self, uow_factory):
        for _ in range(3):
            record(uow_factory, "LOGIN_FAILED", NOON)
        record(uow_factory, "LOGIN_SUCCEEDED", NOON)

        counts = totals_between(
            uow_factory, NOON - timedelta(hours=1), NOON + timedelta(hours=1)
        )

        assert counts == {"LOGIN_FAILED": 3, "LOGIN_SUCCEEDED": 1}

    def test_the_span_excludes_its_end_and_includes_its_start(self, uow_factory):
        """Half-open, like every other span in this codebase: adjacent
        spans that both include their edges count the same event twice."""
        record(uow_factory, "LOGIN_FAILED", NOON)
        record(uow_factory, "LOGIN_FAILED", NOON + timedelta(hours=1))

        counts = totals_between(uow_factory, NOON, NOON + timedelta(hours=1))

        assert counts == {"LOGIN_FAILED": 1}

    def test_a_span_with_nothing_in_it_is_empty_rather_than_absent(
        self, uow_factory
    ):
        counts = totals_between(
            uow_factory,
            NOON - timedelta(days=400),
            NOON - timedelta(days=399),
        )

        assert counts == {}


class TestBucketingASpan:
    """The shape a chart is drawn from."""

    def test_events_land_in_the_interval_they_happened_in(self, uow_factory):
        record(uow_factory, "LOGIN_FAILED", NOON + timedelta(minutes=5))
        record(uow_factory, "LOGIN_FAILED", NOON + timedelta(minutes=35))
        record(uow_factory, "LOGIN_FAILED", NOON + timedelta(minutes=95))

        with uow_factory(read_only=True) as uow:
            buckets = dict(uow.security_events.buckets_between(
                NOON, NOON + timedelta(hours=2), buckets=4
            ))

        # Four half-hours: 12:05 and 12:35 in the first two, 13:35 in the
        # last.
        assert buckets["LOGIN_FAILED"] == [1, 1, 0, 1]

    def test_every_row_has_exactly_as_many_buckets_as_asked_for(
        self, uow_factory
    ):
        """A chart must not have to ask which interval is missing."""
        record(uow_factory, "LOGIN_FAILED", NOON)

        with uow_factory(read_only=True) as uow:
            buckets = dict(uow.security_events.buckets_between(
                NOON - timedelta(hours=6), NOON + timedelta(hours=6), buckets=12
            ))

        assert len(buckets["LOGIN_FAILED"]) == 12

    def test_an_event_at_the_very_end_of_the_span_is_not_lost(
        self, uow_factory
    ):
        """The interval width is floored, so the last moment of a span can
        round one bucket past the end -- and dropping it would mean a
        chart that quietly loses its newest bar."""
        span = timedelta(seconds=10)
        record(uow_factory, "LOGIN_FAILED", NOON + span - timedelta(milliseconds=1))

        with uow_factory(read_only=True) as uow:
            buckets = dict(uow.security_events.buckets_between(
                NOON, NOON + span, buckets=3
            ))

        assert sum(buckets["LOGIN_FAILED"]) == 1


class TestFoldingTheDaysThatAreOver:
    """Written before the rows behind them can be swept."""

    def test_a_finished_day_is_folded_into_a_total(self, uow_factory):
        yesterday = NOON - timedelta(days=1)
        for _ in range(4):
            record(uow_factory, "LOGIN_FAILED", yesterday)

        with uow_factory() as uow:
            written = uow.security_events.fold_days_before(
                NOON.replace(hour=0, minute=0, second=0, microsecond=0)
            )
            uow.commit()

        assert written == 1

        with uow_factory(read_only=True) as uow:
            totals = uow.security_events.day_totals_between(
                yesterday - timedelta(days=1), NOON
            )

        assert [(row[1], row[2]) for row in totals] == [("LOGIN_FAILED", 4)]

    def test_folding_twice_replaces_rather_than_doubles(self, uow_factory):
        """A retried task and a second operator land on the same state."""
        yesterday = NOON - timedelta(days=1)
        record(uow_factory, "LOGIN_FAILED", yesterday)
        midnight = NOON.replace(hour=0, minute=0, second=0, microsecond=0)

        for _ in range(2):
            with uow_factory() as uow:
                uow.security_events.fold_days_before(midnight)
                uow.commit()

        with uow_factory(read_only=True) as uow:
            totals = uow.security_events.day_totals_between(
                yesterday - timedelta(days=1), NOON
            )

        assert [(row[1], row[2]) for row in totals] == [("LOGIN_FAILED", 1)]

    def test_today_is_never_folded(self, uow_factory):
        """A total written for a day still receiving events is wrong as
        soon as the next one lands."""
        midnight = NOON.replace(hour=0, minute=0, second=0, microsecond=0)
        record(uow_factory, "LOGIN_FAILED", NOON)

        with uow_factory() as uow:
            written = uow.security_events.fold_days_before(midnight)
            uow.commit()

        assert written == 0


class TestSweepingTheRowsBehindTheTotals:
    """The table is append-only in practice and must stay finite."""

    def test_rows_older_than_the_cutoff_go(self, uow_factory):
        record(uow_factory, "LOGIN_FAILED", NOON - timedelta(days=100))
        record(uow_factory, "LOGIN_FAILED", NOON)

        with uow_factory() as uow:
            deleted = uow.security_events.delete_before(NOON - timedelta(days=90))
            uow.commit()

        assert deleted == 1

        counts = totals_between(
            uow_factory, NOON - timedelta(days=365), NOON + timedelta(days=1)
        )

        assert counts == {"LOGIN_FAILED": 1}

    def test_the_day_totals_survive_the_sweep(self, uow_factory):
        """Which is the whole point of folding first: the long-range chart
        keeps its past after the rows it was computed from are gone."""
        old = NOON - timedelta(days=100)
        record(uow_factory, "LOGIN_FAILED", old)

        with uow_factory() as uow:
            uow.security_events.fold_days_before(
                NOON.replace(hour=0, minute=0, second=0, microsecond=0)
            )
            uow.security_events.delete_before(NOON - timedelta(days=90))
            uow.commit()

        with uow_factory(read_only=True) as uow:
            totals = uow.security_events.day_totals_between(
                old - timedelta(days=1), NOON
            )

        assert [(row[1], row[2]) for row in totals] == [("LOGIN_FAILED", 1)]

    def test_a_day_chart_reads_the_folded_days_after_the_sweep(
        self, uow_factory
    ):
        """Surviving in the table is not the same as being read.

        The fold was written and never looked at: the chart queried the
        raw rows only, so the sweep took the long-range past with it
        after all -- silently, and only for a deployment whose retention
        is shorter than the span being drawn.
        """
        midnight = NOON.replace(hour=0, minute=0, second=0, microsecond=0)
        old = midnight - timedelta(days=100, hours=-12)
        record(uow_factory, "LOGIN_FAILED", old)

        with uow_factory() as uow:
            uow.security_events.fold_days_before(midnight)
            uow.security_events.delete_before(midnight - timedelta(days=90))
            uow.commit()

        since = midnight - timedelta(days=119)
        until = midnight + timedelta(days=1)
        with uow_factory(read_only=True) as uow:
            series = dict(uow.security_events.buckets_between(since, until, 120))

        counts = series["LOGIN_FAILED"]
        assert sum(counts) == 1
        assert counts[(old.replace(hour=0) - since).days] == 1

    def test_a_folded_day_is_not_counted_twice_before_the_sweep(
        self, uow_factory
    ):
        """Between the fold and the sweep the same events sit in both
        tables, and adding the two would double every day in that
        window."""
        midnight = NOON.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday = midnight - timedelta(hours=12)
        record(uow_factory, "LOGIN_FAILED", yesterday)
        record(uow_factory, "LOGIN_FAILED", yesterday)

        with uow_factory() as uow:
            uow.security_events.fold_days_before(midnight)
            uow.commit()

        since = midnight - timedelta(days=29)
        with uow_factory(read_only=True) as uow:
            series = dict(uow.security_events.buckets_between(
                since, midnight + timedelta(days=1), 30
            ))

        assert sum(series["LOGIN_FAILED"]) == 2

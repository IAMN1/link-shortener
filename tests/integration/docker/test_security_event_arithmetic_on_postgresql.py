"""The seconds arithmetic behind the security counts, on the real engine.

Both repositories now count seconds through ``sql_time.epoch_seconds``;
this file used to say ``_epoch``, a copy of the visit repository's method
under another name, and the copy carried the same fault: ``strftime('%s',
...)`` truncates on SQLite, and casting ``extract(epoch from ...)`` to an
integer *rounds* on PostgreSQL. Rounded, an event at 23:59:59.7 belongs
to the next day -- ``fold_days_before`` writes its total under tomorrow's
date, and ``_lay_the_folded_days_over`` then lays that total on the wrong
column of the chart, replacing what the raw rows said rather than adding
to it.

Only PostgreSQL can show it. Every other test of this repository runs on
SQLite, where the arithmetic is right by accident.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from link_shortener.infrastructure.database.repositories.sqlalchemy_security_event_repository import (
    SQLAlchemySecurityEventRepository,
)


DAY = datetime(2026, 3, 14, tzinfo=timezone.utc)
"""The day every event here belongs to, whatever the fraction says."""

LAST_MOMENT = DAY + timedelta(
    hours=23, minutes=59, seconds=59, microseconds=700000
)
"""Seven tenths of a second before the day ends."""


@pytest.fixture()
def events(app, db_session):
    """
    A repository over the real database, with both tables empty.

    The tables are not among those the directory's cleaner truncates, and
    the fold reads whatever is there, so each test starts from nothing.

    Args:
        app: The application fixture, for its schema.
        db_session: Session against the real PostgreSQL.

    Returns:
        The repository under test.
    """
    db_session.execute(text("DELETE FROM security_event_days"))
    db_session.execute(text("DELETE FROM security_events"))
    db_session.commit()
    yield SQLAlchemySecurityEventRepository(db_session)
    db_session.rollback()


class TestTheLastSecondOfADayBelongsToThatDay:

    def test_a_fractional_second_does_not_fold_into_the_next_day(self, events):
        """
        Measured before the fix on this engine: the day row came back
        dated 2026-03-15 for an event recorded on 2026-03-14.
        """
        events.record("LOGIN_FAILED", LAST_MOMENT)
        events.session.flush()

        assert events.fold_days_before(DAY + timedelta(days=1)) == 1

        folded = events.day_totals_between(DAY, DAY + timedelta(days=2))

        assert [(day, event_type, total) for day, event_type, total in folded] == [
            (DAY, "LOGIN_FAILED", 1)
        ]

    def test_the_daily_chart_counts_the_day_the_event_happened(self, events):
        """
        The symptom an operator sees. A day folded under the wrong date is
        laid over the wrong column, and the fold replaces rather than adds
        -- so the day it belongs to reads empty and the day after it reads
        as one event that never happened then.
        """
        events.record("LOGIN_FAILED", LAST_MOMENT)
        events.session.flush()
        events.fold_days_before(DAY + timedelta(days=1))
        events.session.flush()

        series = events.buckets_between(DAY, DAY + timedelta(days=2), buckets=2)

        assert series == [("LOGIN_FAILED", [1, 0])]

    def test_an_event_stays_in_the_bucket_its_instant_falls_in(self, events):
        """
        The same arithmetic where the hourly chart reads it: an event four
        tenths of a second before a boundary is in the bucket that ends
        there.
        """
        events.record("LOGIN_SUCCEEDED", DAY + timedelta(seconds=3599, microseconds=600000))
        events.session.flush()

        series = events.buckets_between(DAY, DAY + timedelta(days=1), buckets=24)

        assert series[0][1][:2] == [1, 0]

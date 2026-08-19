"""The seconds arithmetic behind every chart, run on the engine it ships on.

``SQLAlchemyLinkVisitRepository`` does its bucketing in the database, and
the two engines spell it differently: SQLite has ``strftime('%s', ...)``,
PostgreSQL has ``extract(epoch from ...)``. The module's own docstring says
what that costs -- "both engines truncate when dividing integers, while
casting a fractional result to an integer *rounds* in PostgreSQL" -- and
then the code cast the fractional result to an integer anyway.

Nothing in ``tests/`` could see it. Every other test of this repository runs
on SQLite, where ``strftime`` truncates and the arithmetic is right by
accident; the defect only exists on the engine a deployment actually uses.
That is the whole reason this file is here rather than beside them.

What rounding does: a visit at 23:59:59.7 is a visit on the next day, so
``roll_up_days`` writes its day row under tomorrow's date. ``daily_totals``
prefers a rolled-up row to the raw rows for the same day -- it has to, or
the folded days would count twice -- so the day that visit belongs to reads
as empty while tomorrow, still filling, reads as already settled and stops
moving.
"""

from datetime import datetime, timedelta, timezone

from link_shortener.domain.entities.link import Link
from link_shortener.domain.entities.link_visit import LinkVisit
from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.url_hash import UrlHash
from link_shortener.infrastructure.database.repositories.sqlalchemy_link_repository import (
    SQLAlchemyLinkRepository,
)
from link_shortener.infrastructure.database.repositories.sqlalchemy_link_visit_repository import (
    SQLAlchemyLinkVisitRepository,
)


DAY = datetime(2026, 3, 14, tzinfo=timezone.utc)
"""The day every visit here belongs to, whatever the fraction says."""


def a_link(session, code, suffix):
    """
    Store a link for the visits to hang off.

    Args:
        session: The session the repository writes through.
        code: Short code, unique to the calling test -- the directory
            shares one ``urls`` table and a repeated code fails the
            unique constraint rather than the assertion.
        suffix: Four hex characters keeping the URL hash unique too.

    Returns:
        The saved link.
    """
    link = Link.create(
        url_hash=UrlHash("e" * 60 + suffix),
        short_code=ShortCode(code),
        original_url=OriginalUrl(f"https://example.com/{code}"),
        owner=None,
        ttl_seconds=0,
    )
    return SQLAlchemyLinkRepository(session).save(link)


def a_visit_at(link_id, moment):
    """
    A visit fixed to one instant, fractions included.

    Args:
        link_id: The link that was opened.
        moment: When, to the microsecond.

    Returns:
        The visit, unsaved.
    """
    return LinkVisit.record(
        link_id=link_id, remote_addr="203.0.113.9", now=moment
    )


class TestTheLastSecondOfADayBelongsToThatDay:

    def test_a_fractional_second_does_not_move_a_visit_to_the_next_day(
        self, app, db_session
    ):
        """
        Rounding put 23:59:59.7 into tomorrow's roll-up row.

        Measured before the fix, on this engine: the day row came back
        dated 2026-03-15 for a visit made on 2026-03-14.
        """
        link = a_link(db_session, "pgeps001", "0001")
        visits = SQLAlchemyLinkVisitRepository(db_session)
        visits.record(
            a_visit_at(link.id, DAY + timedelta(hours=23, minutes=59,
                                                seconds=59, microseconds=700000))
        )
        db_session.flush()

        assert visits.roll_up_days(before=DAY + timedelta(days=1)) == 1

        folded = visits.rolled_days(
            link.id, DAY - timedelta(days=1), DAY + timedelta(days=2)
        )
        assert [row.day for row in folded] == [DAY]
        assert folded[0].total == 1

    def test_the_day_the_chart_draws_is_the_day_the_visit_was_made(
        self, app, db_session
    ):
        """
        The symptom an operator sees, rather than the row underneath it.

        ``daily_totals`` prefers a folded day to the raw rows behind it, so
        a row folded into the wrong day empties the right one.
        """
        link = a_link(db_session, "pgeps002", "0002")
        visits = SQLAlchemyLinkVisitRepository(db_session)
        visits.record(
            a_visit_at(link.id, DAY + timedelta(hours=23, minutes=59,
                                                seconds=59, microseconds=900000))
        )
        db_session.flush()
        visits.roll_up_days(before=DAY + timedelta(days=1))
        db_session.flush()

        series = visits.daily_totals(
            since=DAY, until=DAY + timedelta(days=2), link_id=link.id
        )

        assert [(bucket.at, bucket.total) for bucket in series] == [
            (DAY, 1), (DAY + timedelta(days=1), 0),
        ]

    def test_a_visit_stays_in_the_bucket_its_instant_falls_in(
        self, app, db_session
    ):
        """
        The same arithmetic, one level down, where the hourly chart reads it.

        A visit 0.4 s before a bucket boundary is in the bucket that ends
        there, not the one that starts there.
        """
        link = a_link(db_session, "pgeps003", "0003")
        visits = SQLAlchemyLinkVisitRepository(db_session)
        # Buckets are an hour wide over a day; this instant is inside the
        # first one by four tenths of a second.
        visits.record(
            a_visit_at(link.id, DAY + timedelta(seconds=3599, microseconds=600000))
        )
        db_session.flush()

        summary = visits.summary(
            since=DAY, until=DAY + timedelta(days=1), buckets=24, link_id=link.id
        )

        assert summary.buckets[0].total == 1
        assert summary.buckets[1].total == 0

"""
Integration tests for the aggregates the statistics pages are drawn from.

Bucketing is arithmetic done by the database, in two dialects that spell
it differently, on values whose timezone SQLite does not keep. Every part
of that is a place where a chart can come out subtly wrong -- shifted by
a bucket, double-counted, or silently empty -- while every unit test
still passes. So the counting is checked against rows that were actually
written, at times chosen to land on the edges.
"""

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from link_shortener.domain import (
    Link, LinkVisit, OriginalUrl, OwnerID, ShortCode, UrlHash,
)
from tests.integration.conftest import ensure_user


NOON = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def statements(app):
    """
    Record the SQL a block of code sends, for counting round trips.

    Cost is the point of two checks below, and cost is not visible in a
    return value: a method folding the right numbers with one statement
    per row is correct and unusable.

    Returns:
        A context manager yielding the list the statements land in.
    """
    from contextlib import contextmanager

    from sqlalchemy import event

    engine = app.container.get_db_manager().engine

    @contextmanager
    def recording():
        seen = []

        def note(conn, cursor, statement, parameters, context, executemany):
            seen.append(statement)

        event.listen(engine, "before_cursor_execute", note)
        try:
            yield seen
        finally:
            event.remove(engine, "before_cursor_execute", note)

    with app.app_context():
        yield recording


@pytest.fixture()
def uow_factory(app):
    """Unit of Work factory bound to the integration database."""
    with app.app_context():
        yield app.container.get_uow_factory()


def make_link(uow_factory, code, owner_id=None):
    """
    Store a link the visits can point at.

    Args:
        uow_factory: Factory for Unit of Work instances.
        code: Short code, which also seeds the hash so two links differ.
        owner_id: Account the link belongs to, if any.

    Returns:
        The id of the stored link.
    """
    with uow_factory() as uow:
        if owner_id:
            # `urls.owner_id` is a foreign key: a link cannot belong to an
            # account that is not there.
            ensure_user(uow._session, owner_id)
        link = Link.create(
            url_hash=UrlHash(hashlib.sha256(code.encode()).hexdigest()),
            short_code=ShortCode(code),
            original_url=OriginalUrl(f"https://example.com/{code}"),
            owner=OwnerID(owner_id) if owner_id else None,
        )
        uow.links.save(link)
        uow.commit()
        return link.id


def visit(uow_factory, link_id, at, user_agent=None):
    """
    Record one visit at a chosen moment.

    Args:
        uow_factory: Factory for Unit of Work instances.
        link_id: Link that was opened.
        at: When it was opened.
        user_agent: Header to classify, if any.
    """
    with uow_factory() as uow:
        recorded = LinkVisit.record(
            link_id=link_id, user_agent=user_agent, now=at
        )
        uow.link_visits.record(recorded)
        uow.commit()


class TestSplittingASpanIntoBuckets:

    def test_each_visit_lands_in_the_hour_it_happened(self, uow_factory):
        link = make_link(uow_factory, "buck01")
        for hour, count in ((0, 1), (2, 3), (5, 2)):
            for _ in range(count):
                visit(uow_factory, link, NOON + timedelta(hours=hour))

        with uow_factory() as uow:
            summary = uow.link_visits.summary(
                since=NOON, until=NOON + timedelta(hours=6), buckets=6,
                link_id=link,
            )

        assert [b.total for b in summary.buckets] == [1, 0, 3, 0, 0, 2]
        assert summary.total == 6

    def test_a_visit_on_a_boundary_belongs_to_the_bucket_it_starts(
        self, uow_factory
    ):
        """
        The case that separates truncation from rounding. One second before
        the boundary and exactly on it must fall either side of it; a cast
        that rounds puts both in the later bucket.
        """
        link = make_link(uow_factory, "buck02")
        visit(uow_factory, link, NOON + timedelta(minutes=59, seconds=59))
        visit(uow_factory, link, NOON + timedelta(hours=1))

        with uow_factory() as uow:
            summary = uow.link_visits.summary(
                since=NOON, until=NOON + timedelta(hours=2), buckets=2,
                link_id=link,
            )

        assert [b.total for b in summary.buckets] == [1, 1]

    def test_a_visit_in_the_last_moment_of_the_span_is_still_counted(
        self, uow_factory
    ):
        """
        The right-hand edge, which is where "the last 24 hours" lives.

        A span asked for as ``now - 24h .. now`` is exactly 86400 seconds
        wide, and the index comes from whole seconds -- so a visit in the
        final fraction of a second computes as bucket 24 of 24. Before the
        clamp, that visit was counted by nobody: the chart drew zero and
        the total agreed with it.
        """
        link = make_link(uow_factory, "buck05")
        until = NOON + timedelta(hours=24)
        visit(uow_factory, link, until - timedelta(microseconds=1))

        with uow_factory() as uow:
            summary = uow.link_visits.summary(
                since=NOON, until=until, buckets=24, link_id=link,
            )

        assert summary.total == 1
        assert summary.buckets[-1].total == 1

    def test_a_span_with_nothing_in_it_answers_with_zeroes(self, uow_factory):
        """
        Not ``None`` and not an empty list: a page that cannot tell "no
        visits" from "no answer" says "Loading..." forever.
        """
        link = make_link(uow_factory, "buck03")

        with uow_factory() as uow:
            summary = uow.link_visits.summary(
                since=NOON, until=NOON + timedelta(hours=3), buckets=3,
                link_id=link,
            )

        assert summary.total == 0
        assert [b.total for b in summary.buckets] == [0, 0, 0]
        assert [b.at for b in summary.buckets] == [
            NOON, NOON + timedelta(hours=1), NOON + timedelta(hours=2)
        ]

    def test_visits_outside_the_span_are_not_counted(self, uow_factory):
        link = make_link(uow_factory, "buck04")
        visit(uow_factory, link, NOON - timedelta(seconds=1))
        visit(uow_factory, link, NOON + timedelta(hours=2))
        visit(uow_factory, link, NOON + timedelta(hours=1))

        with uow_factory() as uow:
            summary = uow.link_visits.summary(
                since=NOON, until=NOON + timedelta(hours=2), buckets=2,
                link_id=link,
            )

        assert summary.total == 1


class TestWhatTheBreakdownsSay:

    def test_devices_browsers_and_robots_are_separated(self, uow_factory):
        link = make_link(uow_factory, "brk001")
        phone = ("Mozilla/5.0 (iPhone) AppleWebKit/605 Mobile Safari/604")
        desktop = "Mozilla/5.0 (Windows NT 10.0) Gecko Firefox/121.0"
        robot = "Mozilla/5.0 (compatible; Googlebot/2.1)"

        for agent, times in ((phone, 3), (desktop, 1), (robot, 2)):
            for _ in range(times):
                visit(uow_factory, link, NOON, user_agent=agent)

        with uow_factory() as uow:
            summary = uow.link_visits.summary(
                since=NOON, until=NOON + timedelta(hours=1), buckets=1,
                link_id=link,
            )

        assert summary.total == 6
        assert summary.bots == 2
        # Robots are counted and marked, not discarded: a counter and a
        # chart that disagree are worse than a chart including robots.
        assert summary.buckets[0].bots == 2
        devices = {d.label: d.total for d in summary.devices}
        assert devices["mobile"] == 3
        assert devices["desktop"] == 1
        browsers = {b.label: b.total for b in summary.browsers}
        assert browsers["bot"] == 2

    def test_the_top_links_table_names_codes_not_ids(self, uow_factory):
        quiet = make_link(uow_factory, "topqui")
        busy = make_link(uow_factory, "topbsy")
        visit(uow_factory, quiet, NOON)
        for _ in range(4):
            visit(uow_factory, busy, NOON)

        with uow_factory() as uow:
            summary = uow.link_visits.summary(
                since=NOON, until=NOON + timedelta(hours=1), buckets=1,
            )

        top = [(row.label, row.total) for row in summary.top_links]
        assert ("topbsy", 4) in top
        assert top.index(("topbsy", 4)) < top.index(("topqui", 1))


class TestWhoIsAllowedToSeeWhat:

    def test_an_owner_sees_only_their_own_links(self, uow_factory):
        mine = make_link(uow_factory, "ownmin", owner_id="owner-a")
        theirs = make_link(uow_factory, "ownthr", owner_id="owner-b")
        visit(uow_factory, mine, NOON)
        for _ in range(5):
            visit(uow_factory, theirs, NOON)

        with uow_factory() as uow:
            summary = uow.link_visits.summary(
                since=NOON, until=NOON + timedelta(hours=1), buckets=1,
                owner_id="owner-a",
            )

        assert summary.total == 1

    def test_asking_about_someone_elses_link_returns_zeroes(self, uow_factory):
        """
        Both filters apply together, so a guessed id is not a way through.
        """
        theirs = make_link(uow_factory, "ownoth", owner_id="owner-b")
        visit(uow_factory, theirs, NOON)

        with uow_factory() as uow:
            summary = uow.link_visits.summary(
                since=NOON, until=NOON + timedelta(hours=1), buckets=1,
                link_id=theirs, owner_id="owner-a",
            )

        assert summary.total == 0


class TestKeepingTheShapeOfThePastAfterTheRowsAreGone:

    @pytest.fixture(autouse=True)
    def nothing_folded_yet(self, app):
        """
        Start each of these from an empty visit history.

        The roll-up is global: it folds every link at once and starts from
        the day after the latest row in ``link_visit_days``, because that
        is the day nothing has folded yet. The ``app`` fixture is
        session-scoped and these tables are not scoped by owner, so
        without this a day folded by a neighbouring test moves the
        boundary and the test under it silently folds nothing.
        """
        with app.app_context():
            with app.container.get_db_manager().session() as session:
                session.execute(text("DELETE FROM link_visit_days"))
                session.execute(text("DELETE FROM link_visits"))
                session.commit()
        yield

    def test_days_that_ended_are_folded_into_one_row_each(self, uow_factory):
        link = make_link(uow_factory, "roll01")
        day_one = NOON - timedelta(days=3)
        day_two = NOON - timedelta(days=2)
        visit(uow_factory, link, day_one)
        visit(uow_factory, link, day_one + timedelta(hours=4))
        visit(uow_factory, link, day_two,
              user_agent="Mozilla/5.0 (compatible; Googlebot/2.1)")

        with uow_factory() as uow:
            written = uow.link_visits.roll_up_days(before=NOON - timedelta(days=1))
            uow.commit()

        assert written == 2
        with uow_factory() as uow:
            days = uow.link_visits.rolled_days(
                link, since=NOON - timedelta(days=4), until=NOON
            )

        assert [(d.total, d.bots) for d in days] == [(2, 0), (1, 1)]

    def test_rolling_the_same_day_twice_does_not_double_it(self, uow_factory):
        """
        A retried task and a second operator both land on the same state.
        """
        link = make_link(uow_factory, "roll02")
        visit(uow_factory, link, NOON - timedelta(days=2))

        for _ in range(2):
            with uow_factory() as uow:
                uow.link_visits.roll_up_days(before=NOON - timedelta(days=1))
                uow.commit()

        with uow_factory() as uow:
            days = uow.link_visits.rolled_days(
                link, since=NOON - timedelta(days=3), until=NOON
            )

        assert [d.total for d in days] == [1]

    def test_a_second_night_folds_only_what_the_first_one_left(
        self, uow_factory
    ):
        """
        The nightly task used to re-fold the whole table every time.

        ``roll_up_days`` selected every raw visit before ``before`` with no
        lower bound at all, so each night it grouped the entire retention
        window -- ninety days of raw rows -- and rewrote every day row it
        had already written, to the same numbers. Its own docstring says
        the opposite: "this runs once a day on a handful of rows".

        Counted as day-rows written, which is what the method returns and
        what the operator's line reports.
        """
        link = make_link(uow_factory, "roll10")
        for day in (4, 3, 2):
            visit(uow_factory, link, NOON - timedelta(days=day))

        with uow_factory() as uow:
            first = uow.link_visits.roll_up_days(before=NOON - timedelta(days=1))
            uow.commit()

        # A day nobody had folded yet, arriving after the first night.
        visit(uow_factory, link, NOON - timedelta(days=1, hours=2))

        with uow_factory() as uow:
            second = uow.link_visits.roll_up_days(before=NOON)
            uow.commit()

        assert first == 3
        assert second == 1

    def test_the_second_night_leaves_the_first_night_s_totals_alone(
        self, uow_factory
    ):
        """
        Folding less must not mean losing what was folded before.
        """
        link = make_link(uow_factory, "roll11")
        visit(uow_factory, link, NOON - timedelta(days=3))
        visit(uow_factory, link, NOON - timedelta(days=3, hours=1))

        with uow_factory() as uow:
            uow.link_visits.roll_up_days(before=NOON - timedelta(days=2))
            uow.commit()

        visit(uow_factory, link, NOON - timedelta(days=1))

        with uow_factory() as uow:
            uow.link_visits.roll_up_days(before=NOON)
            uow.commit()

        with uow_factory() as uow:
            days = uow.link_visits.rolled_days(
                link, since=NOON - timedelta(days=5), until=NOON
            )

        assert [d.total for d in days] == [2, 1]

    def test_it_does_not_issue_one_statement_per_day_it_rewrites(
        self, uow_factory, statements
    ):
        """
        The other half of the cost: one ``DELETE`` per ``(link, day)``.

        With a thousand links carrying a quarter each, a night of folding
        was a thousand round trips before the insert -- and it grew with
        the table rather than with the work.
        """
        for index in range(4):
            link = make_link(uow_factory, f"rollq{index}")
            for day in (4, 3, 2):
                visit(uow_factory, link, NOON - timedelta(days=day))

        with statements() as seen:
            with uow_factory() as uow:
                uow.link_visits.roll_up_days(before=NOON - timedelta(days=1))
                uow.commit()

        deletes = [text for text in seen if text.lstrip().upper().startswith("DELETE")]
        assert len(deletes) <= 1, deletes

    def test_the_daily_chart_survives_the_rows_being_deleted(self, uow_factory):
        """
        The whole reason the roll-up exists. After the sweep the raw rows
        for that day are gone, and the day must still have its total.
        """
        link = make_link(uow_factory, "roll03")
        old_day = NOON - timedelta(days=5)
        visit(uow_factory, link, old_day)
        visit(uow_factory, link, old_day + timedelta(hours=2))
        visit(uow_factory, link, NOON)

        with uow_factory() as uow:
            uow.link_visits.roll_up_days(before=NOON - timedelta(days=1))
            uow.commit()
        with uow_factory() as uow:
            deleted = uow.link_visits.delete_raw_before(NOON - timedelta(days=1))
            uow.commit()

        # At least this link's two, and however many its neighbours in this
        # database left behind -- the sweep is service-wide by design.
        assert deleted >= 2

        with uow_factory() as uow:
            daily = uow.link_visits.daily_totals(
                since=NOON - timedelta(days=6), until=NOON + timedelta(days=1),
                link_id=link,
            )

        by_day = {b.at.date(): b.total for b in daily}
        assert by_day[old_day.date()] == 2, "the folded day lost its total"
        assert by_day[NOON.date()] == 1, "the recent day lost its raw visits"

    def test_a_day_present_in_both_places_is_counted_once(self, uow_factory):
        """
        The roll-up does not delete what it folded, so a naive sum of both
        sources counts those days twice -- and the chart quietly doubles.
        """
        link = make_link(uow_factory, "roll04")
        day = NOON - timedelta(days=2)
        visit(uow_factory, link, day)
        visit(uow_factory, link, day + timedelta(hours=1))

        with uow_factory() as uow:
            uow.link_visits.roll_up_days(before=NOON - timedelta(days=1))
            uow.commit()

        with uow_factory() as uow:
            daily = uow.link_visits.daily_totals(
                since=NOON - timedelta(days=3), until=NOON,
                link_id=link,
            )

        assert {b.at.date(): b.total for b in daily}[day.date()] == 2

    def test_the_day_still_running_is_not_folded(self, uow_factory):
        """
        A total written for today is wrong as soon as the next visit lands.
        """
        link = make_link(uow_factory, "roll05")
        visit(uow_factory, link, NOON)

        with uow_factory() as uow:
            uow.link_visits.roll_up_days(before=NOON.replace(hour=0, minute=0))
            uow.commit()

        with uow_factory() as uow:
            days = uow.link_visits.rolled_days(
                link, since=NOON - timedelta(days=1), until=NOON + timedelta(days=1)
            )

        # Asked about this link rather than about the count the sweep
        # returned: the sweep is service-wide, and this database is shared
        # with every other test in the file.
        assert days == []

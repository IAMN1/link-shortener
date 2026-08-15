"""
SQLAlchemy implementation of the ``LinkVisitRepository`` interface.

The interesting part of this module is the bucketing. Splitting a span
into equal intervals has to happen in the database -- a million rows
fetched to be counted in Python is a million rows across the wire -- and
the two engines this project runs on spell the arithmetic differently:
PostgreSQL has ``extract(epoch from ...)``, SQLite has
``strftime('%s', ...)`` and no ``extract`` at all.

Both are made to produce a whole number of seconds, and the bucket index
is then integer division. That matters: both engines truncate when
dividing integers, while casting a fractional result to an integer
*rounds* in PostgreSQL. Rounding would put the visits either side of a
bucket boundary in the wrong column, which is the kind of defect that
never looks like a defect -- the chart just draws a slightly different
shape.
"""

import math
from datetime import datetime, timedelta, timezone
# `cast` is imported twice under two names on purpose: SQLAlchemy's casts
# a column expression to a SQL type, typing's tells the checker what a
# value already is. Sharing the name would make every use ambiguous.
from typing import Dict, List, Optional, cast as as_type

from sqlalchemy import (
    CursorResult, Integer, cast, delete, extract, func, select,
)
from sqlalchemy.orm import Session

from link_shortener.domain import (
    LinkVisit, LinkVisitRepository, VisitBreakdown, VisitBucket, VisitSummary,
    VisitsOnADay,
)
from link_shortener.infrastructure.database.models.link_model import LinkModel
from link_shortener.infrastructure.database.models.link_visit_model import (
    LinkVisitDayModel, LinkVisitModel,
)

DAY = 86400


def _as_utc(moment: datetime) -> datetime:
    """
    Give a moment a timezone if the database handed it back without one.

    SQLite stores no offset, so every datetime read from it is naive and
    comparing one against an aware datetime raises. The values written
    are UTC, so reading them back as UTC is a restoration rather than an
    assumption.

    Args:
        moment: Datetime from the database or from a caller.

    Returns:
        The same moment, marked UTC when it carried no zone.
    """
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


class SQLAlchemyLinkVisitRepository(LinkVisitRepository):
    """
    Recorded visits, and the aggregates the statistics pages read.

    Attributes:
        session: Session owned by the unit of work this repository
            belongs to.
    """

    def __init__(self, session: Session):
        """
        Args:
            session: Active SQLAlchemy session.
        """
        self.session = session

    # ----- writing -----

    def record(self, visit: LinkVisit) -> None:
        """
        Store one visit.

        Args:
            visit: The visit to store.
        """
        self.session.add(
            LinkVisitModel(
                id=visit.id,
                link_id=visit.link_id,
                occurred_at=visit.occurred_at,
                visitor_network=visit.visitor_network,
                device=visit.device,
                browser=visit.browser,
                is_bot=visit.is_bot,
            )
        )

    # ----- reading -----

    def _epoch(self, column):
        """
        Seconds since 1970 as a whole number, in whichever dialect is in use.

        Args:
            column: A datetime column.

        Returns:
            An integer-valued SQL expression.
        """
        if self.session.get_bind().dialect.name == "sqlite":
            return cast(func.strftime("%s", column), Integer)
        return cast(extract("epoch", column), Integer)

    def _scoped(self, statement, link_id: Optional[str], owner_id: Optional[str]):
        """
        Narrow a statement to one link, one owner, or both.

        Both are applied when both are given, so an owner asking about a
        link that is not theirs gets an empty answer rather than somebody
        else's figures.

        Args:
            statement: Select to narrow.
            link_id: Restrict to one link.
            owner_id: Restrict to the links of one account.

        Returns:
            The narrowed statement.
        """
        if link_id is not None:
            statement = statement.where(LinkVisitModel.link_id == link_id)
        if owner_id is not None:
            statement = statement.join(
                LinkModel, LinkModel.id == LinkVisitModel.link_id
            ).where(LinkModel.owner_id == owner_id)
        return statement

    def summary(
        self,
        since: datetime,
        until: datetime,
        buckets: int,
        link_id: Optional[str] = None,
        owner_id: Optional[str] = None,
    ) -> VisitSummary:
        """
        Everything the statistics page shows for one span.

        Four queries: the buckets, the two breakdowns, and the top links.
        Deliberately not one query with four aggregates -- that shape
        needs either four scans behind a single plan or a set of window
        functions SQLite cannot run.

        Args:
            since: Start of the span, inclusive, in UTC.
            until: End of the span, exclusive, in UTC.
            buckets: How many equal intervals to split the span into.
            link_id: Restrict to one link.
            owner_id: Restrict to the links of one account.

        Returns:
            A VisitSummary; zero-filled when nothing happened.
        """
        since, until = _as_utc(since), _as_utc(until)
        buckets = max(1, buckets)
        span = max(1, int((until - since).total_seconds()))
        width = max(1, span // buckets)

        counted = self._clamped(
            self._bucket_counts(since, until, width, link_id, owner_id),
            buckets,
        )
        series = []
        total = bots = 0
        for index in range(buckets):
            at = since + timedelta(seconds=index * width)
            seen = counted.get(index, (0, 0))
            series.append(VisitBucket(at=at, total=seen[0], bots=seen[1]))
            total += seen[0]
            bots += seen[1]

        return VisitSummary(
            since=since,
            until=until,
            total=total,
            bots=bots,
            buckets=series,
            devices=self._breakdown(
                LinkVisitModel.device, since, until, link_id, owner_id
            ),
            browsers=self._breakdown(
                LinkVisitModel.browser, since, until, link_id, owner_id
            ),
            top_links=self._top_links(since, until, owner_id),
        )

    @staticmethod
    def _clamped(counted: Dict[int, tuple], buckets: int) -> Dict[int, tuple]:
        """
        Fold an index that fell off the right-hand edge into the last bucket.

        The edge is reached in ordinary use, not only in theory. A span of
        "the last 24 hours" is exactly 86400 seconds wide, and the bucket
        index is computed from whole seconds -- so a visit in the final
        fraction of a second lands on index 24 of 24 and, unclamped, is
        counted by nobody. Measured: one visit recorded, and both the
        chart and the total said zero.

        Args:
            counted: Bucket index to ``(total, bots)``, as the query
                returned it.
            buckets: How many buckets the caller asked for.

        Returns:
            The same counts with every index inside ``0..buckets - 1``.
        """
        folded: Dict[int, tuple] = {}
        for index, (total, bots) in counted.items():
            slot = min(max(index, 0), buckets - 1)
            seen = folded.get(slot, (0, 0))
            folded[slot] = (seen[0] + total, seen[1] + bots)
        return folded

    def _bucket_counts(
        self,
        since: datetime,
        until: datetime,
        width: int,
        link_id: Optional[str],
        owner_id: Optional[str],
    ) -> Dict[int, tuple]:
        """
        Count visits per bucket index.

        Args:
            since: Start of the span.
            until: End of the span.
            width: Bucket width in seconds.
            link_id: Restrict to one link.
            owner_id: Restrict to the links of one account.

        Returns:
            Mapping of bucket index to ``(total, bots)``.
        """
        # `//`, not `/`. SQLAlchemy renders true division as `x / (n + 0.0)`
        # on SQLite and `x / CAST(n AS NUMERIC)` on PostgreSQL -- both give
        # a fraction, so visits an hour apart land in different "buckets"
        # and one day folds into several rows. Measured: two visits four
        # hours apart produced two rows for the same date.
        index = (
            (self._epoch(LinkVisitModel.occurred_at) - int(since.timestamp()))
            // width
        ).label("bucket")

        statement = select(
            index,
            func.count(LinkVisitModel.id),
            func.sum(cast(LinkVisitModel.is_bot, Integer)),
        ).where(
            LinkVisitModel.occurred_at >= since,
            LinkVisitModel.occurred_at < until,
        )
        statement = self._scoped(statement, link_id, owner_id).group_by(index)

        return {
            int(row[0]): (int(row[1]), int(row[2] or 0))
            for row in self.session.execute(statement)
        }

    def _breakdown(
        self,
        column,
        since: datetime,
        until: datetime,
        link_id: Optional[str],
        owner_id: Optional[str],
    ) -> List[VisitBreakdown]:
        """
        Count visits by the values of one column, largest first.

        Args:
            column: Column to group by.
            since: Start of the span.
            until: End of the span.
            link_id: Restrict to one link.
            owner_id: Restrict to the links of one account.

        Returns:
            Counts against labels, in descending order.
        """
        statement = select(column, func.count(LinkVisitModel.id)).where(
            LinkVisitModel.occurred_at >= since,
            LinkVisitModel.occurred_at < until,
        )
        statement = self._scoped(statement, link_id, owner_id).group_by(
            column
        ).order_by(func.count(LinkVisitModel.id).desc())

        return [
            VisitBreakdown(label=row[0] or "unknown", total=int(row[1]))
            for row in self.session.execute(statement)
        ]

    def _top_links(
        self, since: datetime, until: datetime, owner_id: Optional[str]
    ) -> List[VisitBreakdown]:
        """
        The ten most visited links in the span, by short code.

        The label is the code rather than the id: the id means nothing on
        a page, and joining here saves the caller ten lookups.

        Args:
            since: Start of the span.
            until: End of the span.
            owner_id: Restrict to the links of one account.

        Returns:
            Short codes against visit counts, largest first.
        """
        statement = (
            select(LinkModel.short_code, func.count(LinkVisitModel.id))
            .join(LinkModel, LinkModel.id == LinkVisitModel.link_id)
            .where(
                LinkVisitModel.occurred_at >= since,
                LinkVisitModel.occurred_at < until,
            )
            .group_by(LinkModel.short_code)
            .order_by(func.count(LinkVisitModel.id).desc())
            .limit(10)
        )
        if owner_id is not None:
            statement = statement.where(LinkModel.owner_id == owner_id)

        return [
            VisitBreakdown(label=row[0], total=int(row[1]))
            for row in self.session.execute(statement)
        ]

    def daily_totals(
        self,
        since: datetime,
        until: datetime,
        link_id: Optional[str] = None,
        owner_id: Optional[str] = None,
    ) -> List[VisitBucket]:
        """
        Visits per day, reading the rolled-up days and the raw rows together.

        A day is taken from the roll-up when it has a row there, and from
        the raw visits otherwise. Not summed from both: the roll-up does
        not delete what it folded, so the days that exist in both would
        otherwise be counted twice.

        Args:
            since: First day, inclusive, in UTC.
            until: Last day, exclusive, in UTC.
            link_id: Restrict to one link.
            owner_id: Restrict to the links of one account.

        Returns:
            One bucket per day, in order, zero-filled where nothing
            happened.
        """
        since, until = _as_utc(since), _as_utc(until)
        start = since.replace(hour=0, minute=0, second=0, microsecond=0)
        # Rounded up, so a span ending mid-day still includes that day, and
        # a span ending exactly at midnight does not add an empty one after
        # it -- which is how "the last three days" grew a bucket for
        # tomorrow.
        days = max(1, math.ceil((until - start).total_seconds() / DAY))

        rolled = self._rolled_totals(start, until, link_id, owner_id)
        raw = self._clamped(
            self._bucket_counts(start, until, DAY, link_id, owner_id), days
        )

        series = []
        for index in range(days):
            at = start + timedelta(days=index)
            if at in rolled:
                total, bots = rolled[at]
            else:
                total, bots = raw.get(index, (0, 0))
            series.append(VisitBucket(at=at, total=total, bots=bots))
        return series

    def _rolled_totals(
        self,
        since: datetime,
        until: datetime,
        link_id: Optional[str],
        owner_id: Optional[str],
    ) -> Dict[datetime, tuple]:
        """
        Read the roll-up rows for a span, summed across links.

        Args:
            since: First day, inclusive.
            until: Last day, exclusive.
            link_id: Restrict to one link.
            owner_id: Restrict to the links of one account.

        Returns:
            Mapping of day to ``(total, bots)``.
        """
        statement = select(
            LinkVisitDayModel.day,
            func.sum(LinkVisitDayModel.total),
            func.sum(LinkVisitDayModel.bots),
        ).where(
            LinkVisitDayModel.day >= since,
            LinkVisitDayModel.day < until,
        )
        if link_id is not None:
            statement = statement.where(LinkVisitDayModel.link_id == link_id)
        if owner_id is not None:
            statement = statement.join(
                LinkModel, LinkModel.id == LinkVisitDayModel.link_id
            ).where(LinkModel.owner_id == owner_id)
        statement = statement.group_by(LinkVisitDayModel.day)

        return {
            _as_utc(row[0]): (int(row[1] or 0), int(row[2] or 0))
            for row in self.session.execute(statement)
        }

    def rolled_days(
        self, link_id: str, since: datetime, until: datetime
    ) -> List[VisitsOnADay]:
        """
        Read back the rolled-up days for one link.

        Args:
            link_id: The link.
            since: First day, inclusive.
            until: Last day, exclusive.

        Returns:
            The day rows that exist, in order.
        """
        statement = (
            select(LinkVisitDayModel)
            .where(
                LinkVisitDayModel.link_id == link_id,
                LinkVisitDayModel.day >= _as_utc(since),
                LinkVisitDayModel.day < _as_utc(until),
            )
            .order_by(LinkVisitDayModel.day)
        )
        return [
            VisitsOnADay(
                link_id=row.link_id,
                day=_as_utc(row.day),
                total=row.total,
                bots=row.bots,
            )
            for row in self.session.scalars(statement)
        ]

    # ----- maintenance -----

    def roll_up_days(self, before: datetime) -> int:
        """
        Fold whole days of raw visits into one row per link per day.

        Written as delete-then-insert rather than an upsert, because the
        two engines spell upserts differently and this runs once a day on
        a handful of rows -- the cost of the simpler statement is nothing,
        and the behaviour is identical on both.

        Args:
            before: Fold days earlier than this instant.

        Returns:
            Number of day-rows written.
        """
        before = _as_utc(before)
        day_start = self._epoch(LinkVisitModel.occurred_at) // DAY

        grouped = select(
            LinkVisitModel.link_id,
            day_start.label("day_index"),
            func.count(LinkVisitModel.id),
            func.sum(cast(LinkVisitModel.is_bot, Integer)),
        ).where(
            LinkVisitModel.occurred_at < before
        ).group_by(LinkVisitModel.link_id, day_start)

        rows = [
            (
                row[0],
                datetime.fromtimestamp(int(row[1]) * DAY, tz=timezone.utc),
                int(row[2]),
                int(row[3] or 0),
            )
            for row in self.session.execute(grouped)
        ]
        if not rows:
            return 0

        for link_id, day, _total, _bots in rows:
            self.session.execute(
                delete(LinkVisitDayModel).where(
                    LinkVisitDayModel.link_id == link_id,
                    LinkVisitDayModel.day == day,
                )
            )
        self.session.flush()

        self.session.add_all([
            LinkVisitDayModel(link_id=link_id, day=day, total=total, bots=bots)
            for link_id, day, total, bots in rows
        ])
        return len(rows)

    def delete_raw_before(self, cutoff: datetime) -> int:
        """
        Delete raw visits older than the retention window.

        Args:
            cutoff: Visits recorded before this instant are removed.

        Returns:
            Number of rows deleted.
        """
        # `Result` is the declared return type of `Session.execute`, and it
        # is `CursorResult` that carries a row count. The narrowing is what
        # the checker asks for; the object is the same one either way.
        result = as_type(
            CursorResult,
            self.session.execute(
                delete(LinkVisitModel).where(
                    LinkVisitModel.occurred_at < _as_utc(cutoff)
                )
            )
        )
        return int(result.rowcount or 0)

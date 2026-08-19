"""Counting security events, and folding the days that are over.

The shape and the dialect problems are the ones ``LinkVisitRepository``
already solved, and the solutions are the same ones for the same reasons --
integer division for the bucket index, `strftime` against `extract` for the
epoch. What differs is that there is no owner and no link to scope by: a
security event is about the service.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, cast as as_type

from sqlalchemy import Integer, cast, delete, extract, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from link_shortener.domain.repositories.security_event_repository import (
    SecurityEventRepository,
)
from link_shortener.infrastructure.database.models.security_event_model import (
    SecurityEventDayModel, SecurityEventModel,
)


SECONDS_IN_A_DAY = 86400
"""Length of a day, which is exact because the stamps are UTC.

No offset change ever makes a UTC day longer or shorter, so folding by
``epoch // 86400`` is folding by date -- and it is arithmetic both
dialects do the same way, unlike ``date()`` against ``date_trunc()``.
"""


def _as_utc(moment: datetime) -> datetime:
    """
    Give a moment a timezone if it arrived without one.

    SQLite stores no offset, so every datetime read back from it is
    naive, and comparing one against an aware datetime raises. What was
    written is UTC, so reading it back as UTC restores rather than
    assumes. A naive bound from a caller is read the same way, for the
    same reason the visit repository does it: ``timestamp()`` on a naive
    datetime asks the host what zone it is in, and the answer moves every
    bucket by the machine's offset.

    Args:
        moment: Datetime from the database or from a caller.

    Returns:
        The same moment, marked UTC when it carried no zone.
    """
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _midnight_of(moment: datetime) -> datetime:
    """
    The start of the day a moment falls in.

    Args:
        moment: Any moment, in UTC.

    Returns:
        The same day at 00:00:00.
    """
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


class SQLAlchemySecurityEventRepository(SecurityEventRepository):
    """
    Security event repository over SQLAlchemy.

    Attributes:
        session: The session this repository is bound to.
    """

    def __init__(self, session: Session):
        """
        Args:
            session: Active session, owned by the unit of work.
        """
        self.session = session

    def _epoch(self, column):
        """
        Seconds since 1970 as a whole number, in whichever dialect is in use.

        Args:
            column: A datetime column.

        Returns:
            An integer-valued SQL expression, truncated rather than
            rounded on both engines.
        """
        if self.session.get_bind().dialect.name == "sqlite":
            return cast(func.strftime("%s", column), Integer)
        # `floor` before the cast: `extract` yields the fraction of a
        # second too, and casting a fractional value to an integer
        # *rounds* in PostgreSQL while `strftime` truncates. Rounded, an
        # event at 23:59:59.7 became an event on the next day -- folded
        # under tomorrow's date, and then laid over tomorrow's column of
        # the chart, on the engine every deployment runs.
        return cast(func.floor(extract("epoch", column)), Integer)

    def record(self, event_type: str, occurred_at: datetime) -> None:
        """
        Store one event.

        Args:
            event_type: The event's own name.
            occurred_at: When it happened, in UTC.
        """
        self.session.add(
            SecurityEventModel(
                id=str(uuid.uuid4()),
                event_type=event_type,
                occurred_at=occurred_at,
            )
        )

    def buckets_between(
        self, since: datetime, until: datetime, buckets: int
    ) -> List[Tuple[str, List[int]]]:
        """
        The same counts, split into equal intervals across the span.

        Args:
            since: Start of the span, inclusive.
            until: End of the span, exclusive.
            buckets: How many intervals to split the span into.

        Returns:
            Pairs of event type and a list of exactly ``buckets`` counts,
            oldest first.
        """
        if buckets < 1:
            return []

        since, until = _as_utc(since), _as_utc(until)
        width = max(1, int((until - since).total_seconds()) // buckets)

        # `//`, not `/`: SQLAlchemy renders true division as a fraction on
        # both dialects, and events an hour apart would then land in
        # different fractional "buckets" -- the fault measured on the
        # visits, where two visits four hours apart produced two rows for
        # the same day.
        index = (
            (self._epoch(SecurityEventModel.occurred_at) - int(since.timestamp()))
            // width
        ).label("bucket")

        statement = (
            select(
                SecurityEventModel.event_type,
                index,
                func.count(SecurityEventModel.id),
            )
            .where(
                SecurityEventModel.occurred_at >= since,
                SecurityEventModel.occurred_at < until,
            )
            .group_by(SecurityEventModel.event_type, index)
        )

        counted: Dict[str, List[int]] = {}
        for event_type, bucket, total in self.session.execute(statement):
            row = counted.setdefault(str(event_type), [0] * buckets)
            position = int(bucket)
            # The last interval can take a moment that rounds one past the
            # end, since the width is floored: an event at the very end of
            # the span belongs to the last bucket rather than to one that
            # does not exist.
            if 0 <= position < buckets:
                row[position] += int(total)
            elif position == buckets:
                row[buckets - 1] += int(total)

        self._lay_the_folded_days_over(counted, since, width, buckets)

        return sorted(counted.items(), key=lambda pair: sum(pair[1]), reverse=True)

    def _lay_the_folded_days_over(
        self,
        counted: Dict[str, List[int]],
        since: datetime,
        width: int,
        buckets: int,
    ) -> None:
        """
        Replace whole-day buckets with the folded totals for those days.

        The fold exists so that the sweep can delete the raw rows without
        the long-range chart losing its past. Read only where a bucket is
        exactly one day and lines up with one: a folded day is a total
        between midnights and cannot be split across six-hour intervals,
        and laying it on a bucket that straddles two days would move
        events in time to keep them in view.

        Replace rather than add: folding does not delete what it folded --
        the sweep does, afterwards -- so for as long as both exist, a day
        added from both tables is counted twice.

        Args:
            counted: Series per event type, as read from the raw rows.
                Modified in place.
            since: Start of the span, inclusive.
            width: Seconds in one bucket.
            buckets: How many buckets the span holds.
        """
        if width != SECONDS_IN_A_DAY or since != _midnight_of(since):
            return

        until = since + timedelta(seconds=width * buckets)
        for day, event_type, total in self.day_totals_between(since, until):
            position = int((_as_utc(day) - since).total_seconds()) // width
            if not 0 <= position < buckets:
                continue
            row = counted.setdefault(event_type, [0] * buckets)
            row[position] = total

    def fold_days_before(self, day: datetime) -> int:
        """
        Write the day totals for every day that is over.

        Days are folded from the raw rows and written whole, replacing any
        total already stored for the same day and kind -- so a retried task
        and a second operator land on the same state rather than doubling
        a count.

        Args:
            day: Midnight UTC of the current day.

        Returns:
            How many day-and-kind totals were written.
        """
        # Grouped in SQL by event type and by the day the moment falls
        # in, computed as whole days since the epoch. Written without the
        # grouping this was an aggregate over the whole table, which
        # returns one row of nulls when nothing matches -- and produced
        # the right answer whenever anything did, which is the shape of
        # fault that survives every test written against real data.
        #
        # Days are exact seconds here because the stamps are UTC: no
        # offset changes length, so `epoch // 86400` is the date.
        day_index = (
            self._epoch(SecurityEventModel.occurred_at) // SECONDS_IN_A_DAY
        ).label("day_index")

        statement = (
            select(
                SecurityEventModel.event_type,
                day_index,
                func.count(SecurityEventModel.id),
            )
            .where(SecurityEventModel.occurred_at < day)
            .group_by(SecurityEventModel.event_type, day_index)
        )

        totals: Dict[Tuple[datetime, str], int] = {}
        for event_type, index, count in self.session.execute(statement):
            midnight = datetime.fromtimestamp(
                int(index) * SECONDS_IN_A_DAY, tz=timezone.utc
            )
            totals[(midnight, str(event_type))] = int(count)

        for (midnight, event_type), total in totals.items():
            existing = self.session.get(
                SecurityEventDayModel, (midnight, event_type)
            )
            if existing:
                existing.total = total
            else:
                self.session.add(
                    SecurityEventDayModel(
                        day=midnight, event_type=event_type, total=total
                    )
                )

        return len(totals)

    def delete_before(self, moment: datetime) -> int:
        """
        Remove raw rows older than a moment, leaving the day totals.

        Args:
            moment: Rows recorded before this are deleted.

        Returns:
            How many rows were deleted.
        """
        # `Result` is the declared return type of `Session.execute`, and
        # it is `CursorResult` that carries a row count. The narrowing is
        # what the checker asks for; the object is the same one either way.
        result = as_type(
            CursorResult,
            self.session.execute(
                delete(SecurityEventModel).where(
                    SecurityEventModel.occurred_at < moment
                )
            ),
        )
        return int(result.rowcount or 0)

    def day_totals_between(
        self, since: datetime, until: datetime
    ) -> List[Tuple[datetime, str, int]]:
        """
        The folded day totals inside a span, for the long-range chart.

        Args:
            since: Start of the span, inclusive.
            until: End of the span, exclusive.

        Returns:
            Triples of day, event type and total, oldest first.
        """
        statement = (
            select(
                SecurityEventDayModel.day,
                SecurityEventDayModel.event_type,
                SecurityEventDayModel.total,
            )
            .where(
                SecurityEventDayModel.day >= since,
                SecurityEventDayModel.day < until,
            )
            .order_by(SecurityEventDayModel.day)
        )

        return [
            (row[0], str(row[1]), int(row[2]))
            for row in self.session.execute(statement)
        ]

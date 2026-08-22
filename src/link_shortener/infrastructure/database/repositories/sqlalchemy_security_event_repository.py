"""Counting security events, and folding the days that are over.

The shape and the dialect problems are the ones ``LinkVisitRepository``
already solved, and the arithmetic behind them is shared rather than
solved twice: ``sql_time`` holds the epoch and the day, because they are
properties of the dialect rather than of either table. This file used to
carry a byte-identical copy, and the copy carried the same rounding
defect -- which had to be found and fixed on two branches, in two
commits. What differs here is that there is no owner and no link to scope
by: a security event is about the service.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, cast as as_type

from sqlalchemy import delete, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from link_shortener.domain.repositories.security_event_repository import (
    SecurityEventRepository,
)
from link_shortener.infrastructure.database.models.security_event_model import (
    SecurityEventDayModel, SecurityEventModel,
)
from link_shortener.infrastructure.database.repositories.sql_time import (
    DAY, as_utc as _as_utc, epoch_seconds,
)


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
            (epoch_seconds(self.session, SecurityEventModel.occurred_at)
             - int(since.timestamp()))
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
        if width != DAY or since != _midnight_of(since):
            return

        until = since + timedelta(seconds=width * buckets)
        for day, event_type, total in self.day_totals_between(since, until):
            position = int((_as_utc(day) - since).total_seconds()) // width
            if not 0 <= position < buckets:
                continue
            row = counted.setdefault(event_type, [0] * buckets)
            row[position] = total

    def _first_unfolded_day(self) -> Optional[datetime]:
        """
        Midnight of the first day the fold has not written yet.

        Every kind is folded for every day in one statement, so the latest
        day present is the boundary: everything up to it is done, and the
        day after it is where tonight's work starts.

        Returns:
            The day to start from, or ``None`` when nothing has been
            folded yet and the whole table is the work.
        """
        latest = self.session.execute(
            select(func.max(SecurityEventDayModel.day))
        ).scalar()

        return None if latest is None else _as_utc(latest) + timedelta(days=1)

    def fold_days_before(self, day: datetime) -> int:
        """
        Write the day totals for every day that is over and not folded yet.

        Only those days: the scan starts at the day after the latest row
        in ``security_event_days``, and a first run -- which has none --
        takes everything. Without that bound this grouped the whole
        retention window every night, a year of it, and rewrote every day
        row it had ever written to the same numbers. The visit roll-up was
        given the bound for exactly that reason; this half of the pair was
        left behind, and the two are written from one template.

        A plain insert, as the visit roll-up is. It was a read and a write
        per ``(day, kind)`` pair -- a ``SELECT`` before every row, growing
        with the table rather than with the work -- and with the bound in
        place there is nothing for a read to find. What keeps a day from
        being folded twice is the bound; what keeps two runs at once from
        writing one day twice is the key on ``(day, event_type)``, which
        refuses the second rather than doubling the total.

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
            epoch_seconds(self.session, SecurityEventModel.occurred_at) // DAY
        ).label("day_index")

        statement = select(
            SecurityEventModel.event_type,
            day_index,
            func.count(SecurityEventModel.id),
        ).where(SecurityEventModel.occurred_at < day)

        since = self._first_unfolded_day()
        if since is not None:
            statement = statement.where(SecurityEventModel.occurred_at >= since)

        statement = statement.group_by(SecurityEventModel.event_type, day_index)

        totals: Dict[Tuple[datetime, str], int] = {}
        for event_type, index, count in self.session.execute(statement):
            midnight = datetime.fromtimestamp(
                int(index) * DAY, tz=timezone.utc
            )
            totals[(midnight, str(event_type))] = int(count)

        self.session.add_all([
            SecurityEventDayModel(day=midnight, event_type=event_type, total=total)
            for (midnight, event_type), total in totals.items()
        ])

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

"""The counting half of the audit journal, as the domain sees it.

The journal holds what happened; these rows exist so that "how many"
can be asked at all. The interface is deliberately narrow -- an event
type and a moment go in, counts come out -- because anything wider
would be the journal written a second time in a shape that can disagree
with it.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Tuple


class SecurityEventRepository(ABC):
    """
    Interface for counted security events.

    The counting half of the audit journal. The journal itself holds what
    happened and is read from its end; these rows exist so that "how many
    failed sign-ins in the last ninety days" can be answered at all -- a
    question the file cannot answer, since a filtered read of it reaches
    about an hour and a half of a busy service.

    Aggregation belongs here for the reason it belongs in
    ``LinkVisitRepository``: counting rows into buckets is work the query
    planner does better than a use case fetching them to count in Python.
    """

    @abstractmethod
    def record(self, event_type: str, occurred_at: datetime) -> None:
        """
        Store one event.

        Args:
            event_type: The event's own name, from ``AuditEvent``.
            occurred_at: When it happened, in UTC.
        """
        ...

    @abstractmethod
    def buckets_between(
        self, since: datetime, until: datetime, buckets: int
    ) -> List[Tuple[str, List[int]]]:
        """
        How many of each kind of event fell inside each interval of a span.

        The only way to ask how many events there were: a caller wanting
        the total of a span adds its own buckets up. Answering that
        second question with a second query is what let the two answers
        disagree -- the totals were read from the raw rows while the
        series merged in the folded days, so a chart and the figures
        above it could describe different weeks.

        When an interval is exactly a day long and the span starts at
        midnight, the folded totals in ``security_event_days`` are read
        for the days that have them and the raw rows for the rest. A day
        present in both is taken from the fold once, not added twice:
        folding does not delete what it folded, the sweep does, and
        between the two the same events sit in both tables.

        Args:
            since: Start of the span, inclusive, in UTC.
            until: End of the span, exclusive, in UTC.
            buckets: How many equal intervals to split the span into.

        Returns:
            Pairs of event type and a list of ``buckets`` counts, oldest
            first. Every list has exactly ``buckets`` entries, so a chart
            can draw them without asking which interval is missing. A kind
            that did not occur at all is absent rather than present as a
            row of zeroes: the vocabulary is the application's and this is
            a report of what happened, not a form to fill in.
        """
        ...

    @abstractmethod
    def fold_days_before(self, day: datetime) -> int:
        """
        Write the day totals for every day that is over, then say how many.

        The current day is never folded: a total written for a day still
        receiving events is wrong as soon as the next one lands.

        Days already folded are not folded again. A run begins at the day
        after the latest one written, so a repeat over a span an earlier
        run finished finds no work -- which is what makes a retried task
        safe. Two runs that overlap are refused rather than merged: the
        key on ``(day, event_type)`` rejects the second, whose transaction
        rolls back whole, and no day is doubled either way.

        Args:
            day: Midnight UTC of the current day; everything before it is
                folded.

        Returns:
            How many day-and-kind totals were written.
        """
        ...

    @abstractmethod
    def delete_before(self, moment: datetime) -> int:
        """
        Remove raw rows older than a moment, leaving the day totals.

        Args:
            moment: Rows recorded before this are deleted.

        Returns:
            How many rows were deleted.
        """
        ...

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
    def counts_between(
        self, since: datetime, until: datetime
    ) -> List[Tuple[str, int]]:
        """
        How many of each kind of event fell inside a span.

        Args:
            since: Start of the span, inclusive, in UTC.
            until: End of the span, exclusive, in UTC.

        Returns:
            Pairs of event type and count, for the kinds that occurred.
            A kind that did not occur is absent rather than present with a
            zero: the vocabulary is the application's and this is a report
            of what happened, not a form to fill in.
        """
        ...

    @abstractmethod
    def buckets_between(
        self, since: datetime, until: datetime, buckets: int
    ) -> List[Tuple[str, List[int]]]:
        """
        The same counts, split into equal intervals across the span.

        Args:
            since: Start of the span, inclusive, in UTC.
            until: End of the span, exclusive, in UTC.
            buckets: How many equal intervals to split the span into.

        Returns:
            Pairs of event type and a list of ``buckets`` counts, oldest
            first. Every list has exactly ``buckets`` entries, so a chart
            can draw them without asking which interval is missing.
        """
        ...

    @abstractmethod
    def fold_days_before(self, day: datetime) -> int:
        """
        Write the day totals for every day that is over, then say how many.

        The current day is never folded: a total written for a day still
        receiving events is wrong as soon as the next one lands.

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

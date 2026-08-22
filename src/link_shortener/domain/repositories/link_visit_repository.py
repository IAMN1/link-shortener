from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional

from link_shortener.domain.entities.link_visit import (
    LinkVisit, VisitBucket, VisitSummary, VisitsOnADay,
)


class LinkVisitRepository(ABC):
    """
    Interface for recorded visits and the figures drawn from them.

    Aggregation belongs here rather than in a use case: counting a
    million rows into twenty-four buckets is a job for the database, and
    a use case that fetched them to count in Python would move the whole
    table across the wire to do arithmetic the query planner does better.
    """

    @abstractmethod
    def record(self, visit: LinkVisit) -> None:
        """
        Store one visit.

        Args:
            visit: The visit to store.
        """
        ...

    @abstractmethod
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

        Read from the raw visits alone, and not from the folded days --
        which is a limit rather than an oversight. Three of the four
        figures it returns are breakdowns by device, by browser and by
        link, and a folded day keeps none of those: it is a total and a
        robot count. Filling the timeline from the fold while the
        breakdowns beside it still came from the raw rows would answer one
        question with two vocabularies, and the page would show a span of
        ninety visits split across a handful of devices.

        So this reaches back exactly as far as the retention window does,
        while ``daily_totals`` reaches further. On the seeded ninety days
        the two agree; shorten the window and the long span drawn from
        here shrinks with it while the daily chart below keeps its shape.

        Args:
            since: Start of the span, inclusive, in UTC.
            until: End of the span, exclusive, in UTC.
            buckets: How many equal intervals to split the span into.
            link_id: Restrict to one link.
            owner_id: Restrict to the links of one account. Applied
                together with ``link_id`` when both are given, so an owner
                asking about somebody else's link gets zeroes rather than
                somebody else's figures.

        Returns:
            A VisitSummary. A span with no visits comes back with zeroes
            and empty buckets rather than as ``None``: "nothing happened"
            is an answer, and a page that has to tell it apart from "no
            data" ends up saying "Loading..." forever.
        """
        ...

    @abstractmethod
    def daily_totals(
        self,
        since: datetime,
        until: datetime,
        link_id: Optional[str] = None,
        owner_id: Optional[str] = None,
    ) -> List[VisitBucket]:
        """
        Visits per day over a span that may reach past the raw rows.

        Reads the rolled-up days and the raw visits together, because the
        retention window cuts the raw table but not the question. Days
        with no visits are present with a zero, so the caller draws a
        gap rather than joining two distant points with a straight line.

        Args:
            since: First day, inclusive, in UTC.
            until: Last day, exclusive, in UTC.
            link_id: Restrict to one link.
            owner_id: Restrict to the links of one account.

        Returns:
            One bucket per day, in order.
        """
        ...

    @abstractmethod
    def roll_up_days(self, before: datetime) -> int:
        """
        Fold whole days of raw visits into one row per link per day.

        Only days strictly before ``before`` are folded: the current day
        is still receiving visits, and a total written for it would be
        wrong the moment the next one arrives.

        Rolling twice over the same day must not double it, and two
        different things see to that. A run begins at the day after the
        latest one already folded, so a repeat over a span an earlier run
        finished finds no work and writes nothing -- that bound is what
        makes a retried task safe, rather than any rewriting of rows.

        Two runs that overlap -- both reading that boundary before either
        has committed -- are refused rather than merged: the key on
        ``(link_id, day)`` rejects the second, and its transaction rolls
        back whole. The totals the first wrote stand, and no day is
        doubled. Measured against PostgreSQL: the loser raises
        ``UniqueViolation`` and the table holds one correct row.

        Args:
            before: Fold days earlier than this instant.

        Returns:
            Number of day-rows written.
        """
        ...

    @abstractmethod
    def delete_raw_before(self, cutoff: datetime) -> int:
        """
        Delete raw visits older than the retention window.

        Args:
            cutoff: Visits recorded before this instant are removed.

        Returns:
            Number of rows deleted.
        """
        ...

    @abstractmethod
    def rolled_days(
        self, link_id: str, since: datetime, until: datetime
    ) -> List[VisitsOnADay]:
        """
        Read back the rolled-up days for one link.

        Exists for the tests and for the maintenance commands: the pages
        go through ``daily_totals``, which already merges both sources.

        Args:
            link_id: The link.
            since: First day, inclusive.
            until: Last day, exclusive.

        Returns:
            The day rows that exist, in order. Days with no row are
            absent rather than zero-filled.
        """
        ...

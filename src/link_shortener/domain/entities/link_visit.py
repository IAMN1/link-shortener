from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import uuid

from link_shortener.domain.value_objects.visitor import (
    anonymise_address, classify_client,
)


@dataclass
class LinkVisit:
    """
    One recorded opening of a short link.

    The counter on the link answers "how many"; this answers "when", and
    that is the whole difference. ``urls.clicks`` cannot say whether four
    hundred openings happened last Tuesday or over four months, which
    rules out every chart with time on one axis -- and a chart with time
    on one axis is what statistics mostly is.

    What is kept about the visitor is deliberately coarse: the network
    rather than the address, a device class and a browser family rather
    than the string that named them. The reduction happens on the way in
    (see ``domain.value_objects.visitor``), so no row ever holds the
    original.

    Attributes:
        id: Unique identifier (UUID string).
        link_id: The link that was opened.
        occurred_at: When it was opened, in UTC.
        visitor_network: Network the request came from, host part zeroed.
        device: ``desktop``, ``mobile``, ``tablet`` or ``unknown``.
        browser: Browser family, ``bot``, or ``unknown``.
        is_bot: Whether the client announced itself as automated.
    """
    id: str
    link_id: str
    occurred_at: datetime
    visitor_network: Optional[str] = None
    device: str = "unknown"
    browser: str = "unknown"
    is_bot: bool = False

    @classmethod
    def record(
        cls,
        link_id: str,
        remote_addr: Optional[str] = None,
        user_agent: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> "LinkVisit":
        """
        Build a visit from what the request carried.

        Takes the raw address and header rather than reduced values, so
        that the reduction cannot be skipped by a caller who has both to
        hand. There is no constructor path that stores an address.

        Args:
            link_id: The link that was opened.
            remote_addr: Client address as the request reported it.
            user_agent: The ``User-Agent`` header, if it was sent.
            now: Time of the visit; defaults to the current UTC time.

        Returns:
            A LinkVisit ready to be saved.
        """
        device, browser, is_bot = classify_client(user_agent)
        return cls(
            id=str(uuid.uuid4()),
            link_id=link_id,
            occurred_at=now or datetime.now(timezone.utc),
            visitor_network=anonymise_address(remote_addr),
            device=device,
            browser=browser,
            is_bot=is_bot,
        )


@dataclass
class VisitsOnADay:
    """
    Visits to one link on one day, as kept once the raw rows are gone.

    Raw visits are deleted after their retention window, and a chart that
    only reaches back as far as the raw rows would quietly lose its own
    history -- the year-long view would show three months and no gap.
    Rolling each day into a row keeps the shape of the past at a fixed
    cost of one row per link per day.

    Attributes:
        link_id: The link these visits belong to.
        day: The day, at midnight UTC.
        total: Visits recorded that day.
        bots: How many of them announced themselves as automated.
    """
    link_id: str
    day: datetime
    total: int
    bots: int = 0


@dataclass
class VisitBucket:
    """
    One column of a chart: a moment and how many visits fell into it.

    Attributes:
        at: Start of the interval, in UTC.
        total: Visits in the interval, robots included.
        bots: How many of those were robots, so a page can subtract them
            without asking a second question.
    """
    at: datetime
    total: int = 0
    bots: int = 0


@dataclass
class VisitBreakdown:
    """
    A count against a label, for the "top X" tables.

    Attributes:
        label: Device class, browser family, or short code -- whichever
            the breakdown was asked for. Not the visitor's network: that
            is recorded on the row and no breakdown reads it.
        total: How many visits carried it.
    """
    label: str
    total: int = 0


@dataclass
class VisitSummary:
    """
    Everything the statistics page shows about one span of time.

    Assembled by the repository in as few queries as it can manage, rather
    than by the page asking six times.

    Attributes:
        since: Start of the span, in UTC.
        until: End of the span, in UTC.
        total: Visits in the span.
        bots: How many were robots.
        buckets: The span split into equal intervals, in order.
        devices: Visits by device class, largest first.
        browsers: Visits by browser family, largest first.
        top_links: Links with the most visits in the span, largest first.
    """
    since: datetime
    until: datetime
    total: int = 0
    bots: int = 0
    buckets: list = field(default_factory=list)
    devices: list = field(default_factory=list)
    browsers: list = field(default_factory=list)
    top_links: list = field(default_factory=list)

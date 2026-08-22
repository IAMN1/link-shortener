import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, Integer, String,
)
from sqlalchemy.orm import Mapped, mapped_column

from link_shortener.infrastructure.database.models.base import Base


class LinkVisitModel(Base):
    """
    ORM model for one recorded opening of a short link.

    Maps to ``link_visits``. One row per redirect served, written by the
    background task that already updates the counter, so the redirect
    itself is not made slower by it.

    The table is append-only in practice and is the largest one in the
    schema by some distance -- which is why the retention sweep and the
    daily roll-up exist, and why the columns are as narrow as they are.

    Attributes:
        id: UUID primary key.
        link_id: The link that was opened. ``CASCADE``: visits to a link
            that no longer exists are not statistics, they are litter.
        occurred_at: When it was opened, in UTC.
        visitor_network: The network the request came from, host part
            zeroed. Never a full address -- see
            ``domain.value_objects.visitor``.
        device: ``desktop``, ``mobile``, ``tablet`` or ``unknown``.
        browser: Browser family, ``bot``, or ``unknown``.
        is_bot: Whether the client announced itself as automated. A
            separate column rather than ``browser == 'bot'`` because
            every chart filters on it, and a comparison against a string
            in a hot filter is an index nobody can use well.
    """
    __tablename__ = "link_visits"

    __table_args__ = (
        # The two shapes every query takes: a span for the whole service,
        # and a span for one link. Leading with `link_id` in the second
        # lets the same index serve "this link, last week" and "this link,
        # ever" without a scan.
        Index("ix_link_visits_occurred_at", "occurred_at"),
        Index("ix_link_visits_link_occurred", "link_id", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    link_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("urls.id", ondelete="CASCADE"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    # 45 characters is the widest an IPv6 address gets written, and the
    # width `urls.guest_identifier` already uses -- one width for one kind
    # of value rather than two numbers to keep in step. What the two hold
    # is not the same thing and they are not to be compared: that column
    # keeps a guest's address whole, to count their allowance by, while
    # this one keeps only the network the request came from.
    #
    # Written and, so far, read by nobody: no chart breaks visits down by
    # network. It is kept because it is the only thing on this row that
    # could tell one source of traffic from another after the fact -- a
    # column added later fills with nulls for the past, which is the one
    # thing that cannot be recovered.
    visitor_network: Mapped[str | None] = mapped_column(String(45), nullable=True)
    device: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    browser: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    is_bot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class LinkVisitDayModel(Base):
    """
    ORM model for one link's visits on one day, kept after the raw rows go.

    Maps to ``link_visit_days``. Written by the roll-up, which folds days
    that are over and cannot change; the raw rows behind them are then
    free to be deleted by the retention sweep without the year-long chart
    losing its past.

    The primary key is the pair, and it refuses a second row for a day
    already folded rather than replacing the first: the insert is a plain
    one, not an upsert, so an overlapping run is rolled back by the key
    instead of overwriting what the other wrote. What keeps an ordinary
    repeat from reaching the key at all is the roll-up's own lower bound,
    which starts it at the day after the latest one folded.

    Attributes:
        link_id: The link. ``CASCADE`` for the same reason as above.
        day: Midnight UTC of the day being summarised.
        total: Visits recorded that day, robots included.
        bots: How many of them were robots.
    """
    __tablename__ = "link_visit_days"

    __table_args__ = (
        # The service-wide chart reads this table by day and by nothing
        # else. The primary key leads with `link_id`, and a composite
        # index cannot answer a query that does not name its leading
        # column -- so every such read scanned the whole table, which is
        # the one thing this table exists to avoid, and which grows by a
        # row per link per day for as long as the service runs.
        Index("ix_link_visit_days_day", "day"),
    )

    link_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("urls.id", ondelete="CASCADE"),
        primary_key=True,
    )
    day: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bots: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

"""Security events, kept where they can be counted.

The audit journal is the record of what happened and the place an incident
is reconstructed from; it is a file, read from its end, and answering "how
many failed logins yesterday" from it means scanning. Measured on this
tree, a filtered read of fifty thousand lines costs some 130 ms and reaches
about an hour and a half of a busy service -- so a chart of the last ninety
days cannot come from there at all.

These two tables are the counting half, and they are deliberately thin: an
event type and a moment, nothing else. What happened in detail stays in the
journal, which is the one place it is written. Widening these rows would
make the same event exist twice in two shapes that can disagree -- and the
one that gets read would be the one nobody checks.

The shape follows ``link_visits`` and ``link_visit_days`` exactly, because
it is the same problem: rows that arrive with traffic, a chart that wants
months, and a table that must not grow without bound.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from link_shortener.infrastructure.database.models.base import Base


class SecurityEventModel(Base):
    """
    ORM model for one recorded security event.

    Maps to ``security_events``. One row per event the audit journal
    receives -- a sign-in, a refusal, an account or role changed, a
    journal read -- written beside the journal line rather than instead of
    it.

    Attributes:
        id: UUID primary key.
        event_type: The event's own name, from ``AuditEvent``. Stored as
            text rather than as a database enum: the vocabulary is owned
            by the application and grows there, and a schema change per
            event would be a migration for a line of Python.
        occurred_at: When it happened, in UTC.
    """

    __tablename__ = "security_events"

    __table_args__ = (
        # The two shapes every query takes: a span for all events, and a
        # span for one kind. Leading with `event_type` in the second lets
        # the same index serve "failed logins last week" and "failed
        # logins ever".
        Index("ix_security_events_occurred_at", "occurred_at"),
        Index("ix_security_events_type_occurred", "event_type", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class SecurityEventDayModel(Base):
    """
    ORM model for one kind of event on one day, kept after the rows go.

    Maps to ``security_event_days``. Written by the roll-up, which folds
    days that are over and cannot change; the raw rows behind them are
    then free to be swept without the long-range chart losing its past.

    The primary key is the pair, and it refuses a second row for a day
    already folded rather than replacing the first: the insert is a plain
    one, not an upsert, so an overlapping run is rolled back by the key
    instead of overwriting what the other wrote. What keeps an ordinary
    repeat from reaching the key at all is the fold's own lower bound,
    which starts it at the day after the latest one written -- the same
    arrangement ``link_visit_days`` keeps, since the two are folded from
    one template.

    Attributes:
        day: Midnight UTC of the day being summarised.
        event_type: The kind of event counted.
        total: How many of them happened that day.
    """

    __tablename__ = "security_event_days"

    day: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    event_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    # ``server_default`` as well as ``default``, so that ``create_all``
    # and the migration build the same column: see ``LinkVisitModel``.
    total: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )

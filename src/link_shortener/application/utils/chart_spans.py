"""
The spans a chart may be asked for, and where each one begins and ends.

Here rather than in either use case because both draw from it, and they
are read on the same service: "sign-ins over thirty days" and "redirects
over thirty days" have to mean the same thirty days, or two answers about
one week disagree for a reason nobody can see. They held a copy each, kept
equal by a test that compared the two dictionaries -- which held the names
and the widths together, and said nothing about where a span starts.

That is where they had drifted. The security counts moved a span drawn in
whole days onto the days themselves; the visit charts took the last N days
from the instant the question was asked. Measured at 14:37 UTC, the
thirty-day answers covered windows 9 h 23 min apart, and the visit
buckets began at 14:37 while the axis under them was labelled with dates.
"""

from datetime import datetime, timedelta
from typing import Dict, Tuple


PERIODS: Dict[str, Tuple[timedelta, int]] = {
    "24h": (timedelta(hours=24), 24),
    "7d": (timedelta(days=7), 7 * 4),
    "30d": (timedelta(days=30), 30),
    "90d": (timedelta(days=90), 90),
}
"""What a caller may ask for, and how finely each span is drawn.

Fixed rather than free-form, and the reason is not tidiness: a caller free
to name its own span and bucket count can ask for a million buckets, and
the database will oblige.
"""

DEFAULT_PERIOD = "7d"


def span_of(
    now: datetime, span: timedelta, buckets: int
) -> Tuple[datetime, datetime]:
    """
    Both ends of a span, given how finely it is drawn.

    A span drawn in whole days is moved onto the days themselves: it ends
    at the midnight after now and begins ``buckets`` days before that, so
    every bucket is a date rather than a slice running from whatever time
    of day the question was asked. The last bucket is therefore today,
    still filling up.

    Three things need that. The folded totals in ``security_event_days``
    and ``link_visit_days`` are totals between midnights and cannot be
    laid on a bucket that straddles two days, so without this a fold is
    unreadable and the sweep takes the long-range chart's past with it.
    The axis already labels these buckets with dates, which is only true
    if a bucket is one. And two answers about one service cover the same
    days only if both are cut this way -- which matters whether or not
    they are read side by side, since a reader walks from one page to the
    other carrying the first answer in their head.

    Shorter buckets keep the span as asked: an hour of a 24-hour span
    means the hour that just passed, and rounding it to the clock would
    answer a different question.

    Args:
        now: The moment the question was asked.
        span: How long the span is.
        buckets: How many intervals it is drawn in.

    Returns:
        Start, inclusive, and end, exclusive, both in UTC.
    """
    if buckets < 1 or span / buckets != timedelta(days=1):
        return now - span, now

    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = midnight + timedelta(days=1)
    return end - timedelta(days=buckets), end

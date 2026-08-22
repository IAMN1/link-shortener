"""
Where a span begins, and why both charts have to answer that the same way.

The two use cases held a copy each of the table of spans, and a test held
the two copies equal. What that test could see was the names and the
widths; what it could not see was the alignment, which lives in the code
that turns a span into two moments -- and there the two had drifted. The
security counters moved a span drawn in whole days onto the days
themselves; the visit charts took the last N days from the instant they
were asked.

Measured at 14:37:05 UTC on 2026-03-10, before the two were made one:

    30d   visits   2026-02-08T14:37:05Z .. 2026-03-10T14:37:05Z
    30d   events   2026-02-09T00:00:00Z .. 2026-03-11T00:00:00Z

Nine hours and twenty-three minutes apart, on two charts a reader is
invited to compare. And the visit buckets began at 14:37 while the axis
under them printed dates, so a column labelled "8 February" held the
traffic of an afternoon and the morning after it.
"""

from datetime import datetime, time, timedelta, timezone

import pytest

from link_shortener.application.utils.chart_spans import PERIODS, span_of


AFTERNOON = datetime(2026, 3, 10, 14, 37, 5, tzinfo=timezone.utc)


class TestASpanDrawnInDaysIsDrawnOnTheDays:
    """The spans whose buckets are exactly one day wide."""

    @pytest.mark.parametrize("period", ["30d", "90d"])
    def test_both_ends_land_on_midnight(self, period):
        """
        Args:
            period: A span cut into day-wide buckets.
        """
        span, buckets = PERIODS[period]

        since, until = span_of(AFTERNOON, span, buckets)

        assert since.time() == time(0, 0), since
        assert until.time() == time(0, 0), until

    @pytest.mark.parametrize("period", ["30d", "90d"])
    def test_the_last_bucket_is_today(self, period):
        """Today, still filling up -- not tomorrow, which has nothing in
        it, and not yesterday, which would hide the day being watched."""
        span, buckets = PERIODS[period]

        _, until = span_of(AFTERNOON, span, buckets)

        assert until == AFTERNOON.replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)

    @pytest.mark.parametrize("period", ["30d", "90d"])
    def test_it_covers_as_many_days_as_it_draws(self, period):
        """The alignment must not quietly change the span's length."""
        span, buckets = PERIODS[period]

        since, until = span_of(AFTERNOON, span, buckets)

        assert until - since == span


class TestAShorterBucketKeepsTheSpanAsAsked:
    """An hour of a day is the hour that just passed."""

    @pytest.mark.parametrize("period", ["24h", "7d"])
    def test_the_span_ends_at_the_moment_it_was_asked(self, period):
        """
        Rounding these to the clock would answer a different question:
        "the last 24 hours" is not "yesterday and today so far".

        Args:
            period: A span whose buckets are shorter than a day.
        """
        span, buckets = PERIODS[period]

        since, until = span_of(AFTERNOON, span, buckets)

        assert (since, until) == (AFTERNOON - span, AFTERNOON)


class TestTheGuardsAroundTheArithmetic:

    def test_a_bucketless_span_is_not_divided_by_zero(self):
        """``span / buckets`` is the test for day-width, and a zero here
        would raise before anything could answer."""
        since, until = span_of(AFTERNOON, timedelta(days=30), 0)

        assert (since, until) == (AFTERNOON - timedelta(days=30), AFTERNOON)

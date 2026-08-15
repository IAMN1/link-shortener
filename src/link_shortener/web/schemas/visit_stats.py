"""
Response models for the recorded-visit endpoints.

Times go out as ISO-8601 with an offset, and the buckets are a list in
order rather than an object keyed by time: a page draws them left to
right, and JSON objects have no order to rely on.
"""

from datetime import datetime
from typing import List

from pydantic import BaseModel, Field

from link_shortener.domain import VisitBreakdown, VisitBucket, VisitSummary


class VisitBucketSchema(BaseModel):
    """
    One column of a chart.

    Attributes:
        at: Start of the interval, in UTC.
        total: Visits in the interval, robots included.
        bots: How many of those were robots, so the page can subtract
            them without asking a second question.
    """
    at: datetime
    total: int
    bots: int

    @classmethod
    def from_domain(cls, bucket: VisitBucket) -> "VisitBucketSchema":
        """
        Build from the domain object.

        Args:
            bucket: The bucket to convert.

        Returns:
            The response model.
        """
        return cls(at=bucket.at, total=bucket.total, bots=bucket.bots)


class VisitBreakdownSchema(BaseModel):
    """
    A count against a label, for the small tables beside the chart.

    Attributes:
        label: Device class, browser family, or short code.
        total: How many visits carried it.
    """
    label: str
    total: int

    @classmethod
    def from_domain(cls, row: VisitBreakdown) -> "VisitBreakdownSchema":
        """
        Build from the domain object.

        Args:
            row: The breakdown row to convert.

        Returns:
            The response model.
        """
        return cls(label=row.label, total=row.total)


class VisitStatsResponse(BaseModel):
    """
    Everything one span of recorded visits amounts to.

    Attributes:
        since: Start of the span, in UTC.
        until: End of the span, in UTC.
        total: Visits in the span, robots included.
        bots: How many were robots.
        buckets: The span split into equal intervals, in order.
        devices: Visits by device class, largest first.
        browsers: Visits by browser family, largest first.
        top_links: Most visited links in the span. Empty for a caller
            without ``stats:view_full``: a short code is somebody's link,
            which is a different disclosure than a count.
    """
    since: datetime
    until: datetime
    total: int
    bots: int
    buckets: List[VisitBucketSchema] = Field(default_factory=list)
    devices: List[VisitBreakdownSchema] = Field(default_factory=list)
    browsers: List[VisitBreakdownSchema] = Field(default_factory=list)
    top_links: List[VisitBreakdownSchema] = Field(default_factory=list)

    model_config = {
        "json_schema_extra": {
            "example": {
                "since": "2026-08-08T12:00:00+00:00",
                "until": "2026-08-15T12:00:00+00:00",
                "total": 1284,
                "bots": 96,
                "buckets": [{"at": "2026-08-08T12:00:00+00:00",
                             "total": 41, "bots": 3}],
                "devices": [{"label": "mobile", "total": 812}],
                "browsers": [{"label": "chrome", "total": 640}],
                "top_links": [{"label": "q68J3qY", "total": 412}],
            }
        }
    }

    @classmethod
    def from_domain(cls, summary: VisitSummary) -> "VisitStatsResponse":
        """
        Build from the domain object.

        Args:
            summary: The summary to convert.

        Returns:
            The response model.
        """
        return cls(
            since=summary.since,
            until=summary.until,
            total=summary.total,
            bots=summary.bots,
            buckets=[VisitBucketSchema.from_domain(b) for b in summary.buckets],
            devices=[VisitBreakdownSchema.from_domain(d) for d in summary.devices],
            browsers=[VisitBreakdownSchema.from_domain(b) for b in summary.browsers],
            top_links=[VisitBreakdownSchema.from_domain(t) for t in summary.top_links],
        )


class DailyVisitsResponse(BaseModel):
    """
    Visits per day over a span that may reach past the raw rows.

    Attributes:
        days: One entry per day, oldest first, zero-filled where nothing
            happened -- so a page draws a gap rather than joining two
            distant points with a straight line.
    """
    days: List[VisitBucketSchema] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, buckets: List[VisitBucket]) -> "DailyVisitsResponse":
        """
        Build from the domain objects.

        Args:
            buckets: One bucket per day, in order.

        Returns:
            The response model.
        """
        return cls(days=[VisitBucketSchema.from_domain(b) for b in buckets])

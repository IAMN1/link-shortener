"""What the counted security events look like on the wire.

Two shapes rather than one, because two questions are asked of the same
span: "how many, in total" fills a row of figures, and "how many, over
time" fills a chart. Sending only the series would make every caller add
them up; sending only the totals would make a chart impossible.

Every series has the same number of buckets, and the bucket boundaries are
implied by ``since``, ``until`` and the count rather than sent per point --
one number against ninety timestamps, for an axis the caller is drawing
anyway.
"""

from datetime import datetime
from typing import Dict, List

from pydantic import BaseModel, ConfigDict

from link_shortener.application.use_cases.security.get_security_counts import (
    SecurityCounts,
)


class SecurityCountsResponse(BaseModel):
    """
    How many security events of each kind fell inside one span.

    Attributes:
        period: The span, echoed back so a page can tell which answer it
            is holding.
        since: Start of the span, in UTC.
        until: End of the span, in UTC.
        buckets: How many equal intervals the span was split into.
        totals: Count per event type over the whole span. Kinds that did
            not occur are absent rather than zero: this is a report of
            what happened, and the vocabulary is the application's.
        series: Count per interval per event type, oldest first.
    """

    period: str
    since: datetime
    until: datetime
    buckets: int
    totals: Dict[str, int]
    series: Dict[str, List[int]]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "since": "2026-08-17T00:00:00Z",
                "until": "2026-08-18T00:00:00Z",
                # The shortest span on offer, written out in full.
                # `buckets` is what a page sizes its axis from and every
                # series has to have exactly that many entries -- the
                # invariant this module opens with -- so an example that
                # abbreviates the arrays contradicts it in the one place a
                # reader looks first. It said `"7d"` with `buckets: 28`
                # and three entries a series.
                "period": "24h",
                "buckets": 24,
                "totals": {"LOGIN_SUCCEEDED": 9, "LOGIN_FAILED": 11},
                "series": {
                    "LOGIN_SUCCEEDED": [
                        0, 0, 0, 0, 0, 0, 1, 0, 2, 0, 1, 0,
                        0, 1, 0, 0, 2, 0, 0, 1, 0, 1, 0, 0,
                    ],
                    "LOGIN_FAILED": [
                        0, 0, 0, 0, 0, 0, 0, 0, 0, 11, 0, 0,
                        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                    ],
                },
            }
        }
    )

    @classmethod
    def from_domain(cls, counts: SecurityCounts) -> "SecurityCountsResponse":
        """
        Build from what the use case returned.

        Args:
            counts: The counts to convert.

        Returns:
            The response model.
        """
        return cls(
            period=counts.period,
            since=counts.since,
            until=counts.until,
            buckets=counts.buckets,
            totals=dict(counts.totals),
            series=dict(counts.series),
        )

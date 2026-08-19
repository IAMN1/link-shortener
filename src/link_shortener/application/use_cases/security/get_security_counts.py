"""
Reading the counted security events into the shapes a chart can draw.

The spans on offer are the ones the visit charts already use, and that is
deliberate rather than lazy: the two sets of figures are read on the same
screen, and a reader comparing "sign-ins" against "redirects" over what
they believe is the same week should not be comparing two different weeks.

Free-form spans are refused for the reason they are refused there too -- a
caller naming its own span and bucket count can ask for a million buckets,
and the database will oblige.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.auth.authorization_service import (
    AuthorizationService,
)
from link_shortener.application.ports.logger.audit import AuditEvent
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.use_cases.admin.privilege_guard import load_actor
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import DomainError, SystemPermissions
from link_shortener.domain.i18n import N_


PERIODS: Dict[str, Tuple[timedelta, int]] = {
    "24h": (timedelta(hours=24), 24),
    "7d": (timedelta(days=7), 7 * 4),
    "30d": (timedelta(days=30), 30),
    "90d": (timedelta(days=90), 90),
}
"""The spans a caller may ask for, and how finely each is drawn.

The same four the visit charts offer, so that two charts on one screen are
about the same week.
"""

DEFAULT_PERIOD = "7d"

REQUIRED_PERMISSION = SystemPermissions.AUDIT_VIEW.value
"""What it takes to see these figures.

The same permission that opens the audit journal, because these numbers
are that journal counted: "eleven failed sign-ins yesterday" is a summary
of lines an operator without `audit:view` may not read, and a count is not
a weaker version of a record -- it is the same information, aggregated.
"""


@dataclass
class SecurityCounts:
    """
    What one span amounted to.

    Attributes:
        period: The span asked for, echoed back so a page redrawn from a
            cached response can tell which one it is holding.
        since: Start of the span, in UTC.
        until: End of the span, in UTC.
        totals: Count per event type, largest first.
        series: Per event type, one count per bucket, oldest first. Every
            list has the same length, so a chart can draw them on one axis
            without asking which interval is missing.
        buckets: How many intervals the span was split into.
    """

    period: str
    since: datetime
    until: datetime
    totals: List[Tuple[str, int]]
    series: List[Tuple[str, List[int]]]
    buckets: int


@dataclass
class GetSecurityCountsUseCase(BaseUseCase):
    """
    Read how many security events of each kind fell inside a span.

    The permission is checked here rather than only on the route, for the
    reason it is checked inside ``ReadJournalUseCase``: the CLI and any
    later caller reach a use case without passing a decorator, and the
    check that matters is the one nearest the data.

    Attributes:
        uow_factory: Opens the read transaction.
        authorization_service: Answers the permission question.
        logger: Where refusals are recorded.
    """

    uow_factory: UnitOfWorkFactory
    authorization_service: AuthorizationService
    logger: Logger

    def execute(
        self,
        context: RequestContext,
        period: str = DEFAULT_PERIOD,
        now: Optional[datetime] = None,
    ) -> SecurityCounts:
        """
        Count the events of a span, by kind and over time.

        Args:
            context: Request context carrying the caller's identity.
            period: One of ``24h``, ``7d``, ``30d``, ``90d``.
            now: End of the span; defaults to the current UTC time.

        Returns:
            The counts and the series behind them.

        Raises:
            DomainError: ``VALIDATION_ERROR`` for a span that is not on
                offer, ``UNAUTHENTICATED`` when nobody is signed in, and
                ``FORBIDDEN`` when the caller lacks ``audit:view``.
        """
        log = self._get_logger(self.logger, context, period=period)

        if period not in PERIODS:
            raise DomainError(
                f"Unknown period '{period}'. Choose one of: "
                + ", ".join(PERIODS),
                code="VALIDATION_ERROR",
                template=N_(
                    "Unknown period '%(period)s'. Choose one of: %(choices)s"
                ),
                params={"period": period, "choices": ", ".join(PERIODS)},
            )

        self._require_may_read(context, log)

        span, buckets = PERIODS[period]
        since, until = self._span_of(
            now or datetime.now(timezone.utc), span, buckets
        )

        with self.uow_factory(read_only=True) as uow:
            series = uow.security_events.buckets_between(since, until, buckets)

        # Added up here rather than counted again in the database. Asked
        # for separately, the two answers were free to disagree -- the
        # totals came from the raw rows while the series could also read
        # the folded days -- and a panel whose figures contradict the
        # chart under them is worse than either number alone.
        totals = sorted(
            ((event_type, sum(counts)) for event_type, counts in series),
            key=lambda pair: pair[1],
            reverse=True,
        )

        return SecurityCounts(
            period=period,
            since=since,
            until=until,
            totals=totals,
            series=series,
            buckets=buckets,
        )

    @staticmethod
    def _span_of(
        now: datetime, span: timedelta, buckets: int
    ) -> Tuple[datetime, datetime]:
        """
        Both ends of a span, given how finely it is drawn.

        A span drawn in whole days is moved onto the days themselves:
        it ends at the midnight after now and begins ``buckets`` days
        before that, so every bucket is a date rather than a slice
        running from whatever time of day the question was asked. The
        last bucket is therefore today, still filling up.

        Two things need that. The folded totals in
        ``security_event_days`` are totals between midnights and cannot
        be laid on a bucket that straddles two days, so without this the
        fold is unreadable and the sweep takes the long-range chart's
        past with it. And the axis already labels these buckets with
        dates, which is only true if a bucket is one.

        Shorter buckets keep the span as asked: an hour of a 24-hour
        span means the hour that just passed, and rounding it to the
        clock would answer a different question.

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

    def _require_may_read(self, context: RequestContext, log: Logger) -> None:
        """
        Check that this caller may see the figures.

        Args:
            context: Request context carrying the caller's identity.
            log: Bound logger.

        Raises:
            DomainError: If the caller may not.
        """
        with self.uow_factory(read_only=True) as uow:
            requester = load_actor(context, uow)

        if self.authorization_service.is_allowed(requester, REQUIRED_PERMISSION):
            return

        # Asked after the check rather than before, so that the refusal is
        # the truthful one: "log in" is the wrong advice for somebody
        # already logged in as the wrong person.
        if requester is None:
            raise DomainError(N_("Authentication required"), code="UNAUTHENTICATED")

        log.warning(
            "Security counts refused", required_permission=REQUIRED_PERMISSION
        )
        raise DomainError(N_("Not authorized"), code="FORBIDDEN")


KNOWN_EVENT_TYPES = tuple(event.value for event in AuditEvent)
"""The vocabulary, offered to a caller that wants to label a chart.

Exported from here rather than read off the counts: a period in which
nothing failed has no ``LOGIN_FAILED`` row, and a chart legend assembled
from the answer would lose a series exactly when it reads as good news.
"""

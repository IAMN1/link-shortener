"""
Reading recorded visits into the shapes a chart can draw.

The spans on offer are fixed rather than free-form, and the reason is
not tidiness: a caller free to name its own span and bucket count can
ask for a million buckets, and the database will oblige.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import DomainError, ShortCode, VisitSummary


# What a caller may ask for, and how finely each span is drawn. A free
# choice of span and bucket count would let one request ask for a million
# buckets, and the query planner would oblige.
PERIODS = {
    "24h": (timedelta(hours=24), 24),
    "7d": (timedelta(days=7), 7 * 4),
    "30d": (timedelta(days=30), 30),
    "90d": (timedelta(days=90), 90),
}
DEFAULT_PERIOD = "7d"


@dataclass
class GetVisitStatsUseCase(BaseUseCase):
    """
    Read the recorded visits for a span, for the service or for one link.

    Who may see what is decided here rather than by the route, because
    the answer depends on the row: a link's own owner may see its visits,
    and so may a holder of ``stats:view_any``, and nobody else may see
    either. A decorator can only ask "is anybody signed in".

    Attributes:
        uow_factory: Opens the read transaction.
        logger: Where refusals and slow reads are recorded.
    """

    uow_factory: UnitOfWorkFactory
    logger: Logger

    def execute(
        self,
        context: RequestContext,
        *,
        period: str = DEFAULT_PERIOD,
        short_code: Optional[str] = None,
        owner_id: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> VisitSummary:
        """
        Summarise visits over one of the offered spans.

        Args:
            context: Request context, for logging.
            period: One of ``24h``, ``7d``, ``30d``, ``90d``.
            short_code: Restrict to one link, by its code.
            owner_id: Restrict to the links of one account. Applied with
                ``short_code`` when both are given, so an owner asking
                about a link that is not theirs gets zeroes.
            now: End of the span; defaults to the current time.

        Returns:
            A VisitSummary, zero-filled when nothing was recorded.

        Raises:
            DomainError: With code ``VALIDATION_ERROR`` when the period is
                not one of the offered ones, or the code is malformed.
        """
        log = self._get_logger(self.logger, context)

        if period not in PERIODS:
            raise DomainError(
                f"Unknown period '{period}'. Choose one of: "
                f"{', '.join(PERIODS)}",
                code="VALIDATION_ERROR",
            )
        span, buckets = PERIODS[period]

        link_id = None
        if short_code is not None:
            try:
                code = ShortCode(short_code)
            except ValueError as invalid:
                raise DomainError(
                    f"Invalid short code: {short_code}", code="VALIDATION_ERROR"
                ) from invalid
            with self.uow_factory(read_only=True) as uow:
                link = uow.links.find_by_code(code)
            if link is None:
                # The same answer as a link that exists but has no visits.
                # Which of the two it is, is not this endpoint's to tell:
                # the info endpoint already decides who may learn that a
                # code exists.
                link_id = "no-such-link"
            else:
                link_id = link.id

        until = now or datetime.now(timezone.utc)
        since = until - span

        with self.uow_factory(read_only=True) as uow:
            summary = uow.link_visits.summary(
                since=since,
                until=until,
                buckets=buckets,
                link_id=link_id,
                owner_id=owner_id,
            )

        log.debug(
            "Visit statistics read",
            period=period,
            total=summary.total,
            scoped_to_link=short_code is not None,
        )
        return summary

    def daily(
        self,
        context: RequestContext,
        *,
        days: int = 90,
        short_code: Optional[str] = None,
        owner_id: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> list:
        """
        Visits per day, reaching past the retention window.

        Separate from ``execute`` because it reads a different pair of
        tables: whole days come from the roll-up, recent ones from the raw
        rows. Asking for a year here is answerable; asking for a year of
        hourly buckets is not.

        Args:
            context: Request context, for logging.
            days: How many days back to go, at most 730.
            short_code: Restrict to one link, by its code.
            owner_id: Restrict to the links of one account.
            now: End of the span; defaults to the current time.

        Returns:
            One bucket per day, oldest first.

        Raises:
            DomainError: With code ``VALIDATION_ERROR`` when ``days`` is
                outside 1..730 or the code is malformed.
        """
        if not 1 <= days <= 730:
            raise DomainError(
                f"days must be between 1 and 730, got {days}",
                code="VALIDATION_ERROR",
            )

        link_id = None
        if short_code is not None:
            try:
                code = ShortCode(short_code)
            except ValueError as invalid:
                raise DomainError(
                    f"Invalid short code: {short_code}", code="VALIDATION_ERROR"
                ) from invalid
            with self.uow_factory(read_only=True) as uow:
                link = uow.links.find_by_code(code)
            link_id = link.id if link is not None else "no-such-link"

        # Whole days, ending with today: the span runs to midnight tonight
        # rather than to this instant, so "3 days" is the day before
        # yesterday, yesterday and today -- not those three and a fourth
        # bucket for tomorrow, which is what asking for `now + 1 day` gave.
        moment = now or datetime.now(timezone.utc)
        tomorrow = moment.replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        since = tomorrow - timedelta(days=days)

        with self.uow_factory(read_only=True) as uow:
            series = uow.link_visits.daily_totals(
                since=since,
                until=tomorrow,
                link_id=link_id,
                owner_id=owner_id,
            )

        self._get_logger(self.logger, context).debug(
            "Daily visit series read", days=days, scoped_to_link=short_code is not None
        )
        return series

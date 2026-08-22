"""
Reading recorded visits into the shapes a chart can draw.

The spans on offer, and where each one begins, come from
``application.utils.chart_spans`` -- shared with the security counters
rather than copied, because the two are read about one service and a
reader comparing "redirects this month" with "sign-ins this month" is
entitled to the same month.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.application.utils.chart_spans import (
    DEFAULT_PERIOD, PERIODS, span_of,
)
from link_shortener.domain import DomainError, ShortCode, VisitSummary
from link_shortener.domain.i18n import N_


@dataclass
class GetVisitStatsUseCase(BaseUseCase):
    """
    Read the recorded visits for a span, for the service or for one link.

    Who may see what is decided by the route, in
    ``_require_may_read_one_links_traffic``, and this takes the answer as
    two filters: ``link_id`` for the link that was allowed and
    ``owner_id`` for the account a caller is confined to. The decision
    does depend on the row -- a link's own owner may see its visits, and
    so may an administrator or a holder of ``stats:view_any``, and nobody
    else may see either -- but the row is one the route has already
    loaded to make that decision. Loading it a second time here is what
    the guard was changed to stop doing: measured, two identical
    ``SELECT ... FROM urls`` and four pool checkouts per call, on an
    endpoint a chart polls every ten seconds.

    So the filters arrive decided, and applying them is all that happens
    here: both are applied together when both are given, which is what
    makes an owner asking about a link that is not theirs get zeroes
    rather than somebody else's figures.

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
        link_id: Optional[str] = None,
        owner_id: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> VisitSummary:
        """
        Summarise visits over one of the offered spans.

        Args:
            context: Request context, for logging.
            period: One of ``24h``, ``7d``, ``30d``, ``90d``.
            short_code: Restrict to one link, by its code. Looked up here.
            link_id: Restrict to one link whose id the caller already
                holds. Both name one link and only one may be given: the
                web routes check who may see a link before asking for its
                traffic, which means they have looked it up already, and
                passing the code as well made the same
                ``SELECT ... FROM urls`` run twice per request -- on an
                endpoint a chart polls every ten seconds.
            owner_id: Restrict to the links of one account. Applied with
                either of the two above, so an owner asking about a link
                that is not theirs gets zeroes.
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
                      template=N_(
                          "Unknown period '%(period)s'. Choose one of: %(choices)s"
                      ),
                      params={"period": period, "choices": ", ".join(PERIODS)},
                  )
        span, buckets = PERIODS[period]

        if link_id is None and short_code is not None:
            # No handler around this. It used to be wrapped in one that
            # caught `ValueError` and re-raised a `DomainError` saying
            # "Invalid short code"; `ShortCode` raises `ValidationError`,
            # which descends from `DomainError` rather than `ValueError`,
            # so the handler never ran and the wording it produced was
            # never seen. What is raised instead carries the same
            # `VALIDATION_ERROR` code -- the same status, out of the same
            # translation catalogue -- and says which lengths are allowed,
            # which the replacement did not.
            code = ShortCode(short_code)
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

        since, until = span_of(now or datetime.now(timezone.utc), span, buckets)

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
        link_id: Optional[str] = None,
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
            short_code: Restrict to one link, by its code. Looked up here.
            link_id: Restrict to one link whose id the caller holds
                already. See ``execute`` for why both exist.
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
                      template=N_("days must be between 1 and 730, got %(days)s"),
                      params={"days": days},
                  )

        if link_id is None and short_code is not None:
            # No handler around this. It used to be wrapped in one that
            # caught `ValueError` and re-raised a `DomainError` saying
            # "Invalid short code"; `ShortCode` raises `ValidationError`,
            # which descends from `DomainError` rather than `ValueError`,
            # so the handler never ran and the wording it produced was
            # never seen. What is raised instead carries the same
            # `VALIDATION_ERROR` code -- the same status, out of the same
            # translation catalogue -- and says which lengths are allowed,
            # which the replacement did not.
            code = ShortCode(short_code)
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

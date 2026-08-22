"""
Folding finished days of visits, and sweeping the rows behind them.

The two halves of keeping a visit table useful and finite: the roll-up
writes what each day amounted to, and only then may the sweep delete the
rows it was computed from.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class RollUpVisitsUseCase(BaseUseCase):
    """
    Use case: fold finished days of visits, then delete the rows behind them.

    Two steps, in this order, and the order is the whole point. Folding
    first means the day totals exist before the raw rows go; sweeping
    first would delete the history and leave the long-range chart with a
    flat nothing where the past used to be, unrecoverably.

    The current day is never folded: a total written for a day that is
    still receiving visits is wrong as soon as the next one lands.

    Attributes:
        uow_factory: Opens the transaction each step runs in.
        logger: Where the outcome is recorded.
        retention_days: How long a raw visit row is kept. Zero disables
            the sweep, and the table then grows without limit -- the
            roll-up still runs, so the daily chart stays correct either
            way.

            The default is the same number as ``VISIT_RETENTION_DAYS``,
            which is where it comes from in a running service, and the
            same number again as the longest span the charts offer. Two
            defaults that disagree are a service whose history is one
            length and whose tests are another, and nothing says which is
            meant. Its twin next door says this too; a test holds both to
            the configuration rather than to a number typed twice.
    """

    uow_factory: UnitOfWorkFactory
    logger: Logger
    retention_days: int = 90

    def execute(
        self, context: RequestContext, now: Optional[datetime] = None
    ) -> Tuple[int, int]:
        """
        Fold the days that are over, then sweep what is past retention.

        Args:
            context: Request context, for logging.
            now: Reference time; defaults to the current UTC time.

        Returns:
            A pair of ``(days folded, raw rows deleted)``.
        """
        log = self._get_logger(self.logger, context)
        moment = now or datetime.now(timezone.utc)
        today = moment.replace(hour=0, minute=0, second=0, microsecond=0)

        with self.uow_factory() as uow:
            folded = uow.link_visits.roll_up_days(before=today)
            uow.commit()

        swept = 0
        if self.retention_days > 0:
            cutoff = today - timedelta(days=self.retention_days)
            with self.uow_factory() as uow:
                swept = uow.link_visits.delete_raw_before(cutoff)
                uow.commit()

        log.info(
            "Visit history rolled up",
            days_folded=folded,
            rows_deleted=swept,
            retention_days=self.retention_days,
        )
        return folded, swept

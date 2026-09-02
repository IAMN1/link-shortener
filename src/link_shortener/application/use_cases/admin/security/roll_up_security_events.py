"""
Folding finished days of security events, and sweeping the rows behind them.

The same two halves as the visit roll-up next door, in the same order and
for the same reason: the day totals must exist before the rows they were
computed from are deleted, or the long-range chart loses its past
permanently.

A use case and a command of its own rather than a step added to
``roll-up-visits``. The two tables fill at different rates -- one with
every redirect, the other with every sign-in -- and an operator whose cron
line says "roll up visits" should not find it also deleting the security
history under a name that does not mention it.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class RollUpSecurityEventsUseCase(BaseUseCase):
    """
    Use case: fold finished days of security events, then sweep the rows.

    The current day is never folded: a total written for a day that is
    still receiving events is wrong as soon as the next one lands.

    Attributes:
        uow_factory: Opens the transaction each step runs in.
        logger: Where the outcome is recorded.
        audit_logger: Where the sweep of this journal's own rows is
            recorded -- in the journal being swept. NIST SP 800-53 AU-9
            asks for exactly that: a trail that can be pruned without the
            pruning appearing in it protects nothing from the people who
            can prune it.
        retention_days: How long a raw event row is kept. Zero disables
            the sweep, and the table then grows without limit -- the fold
            still runs, so the charts stay correct either way.

            The default is the same number as
            ``SECURITY_EVENT_RETENTION_DAYS``, which is where it comes
            from in a running service. Two defaults that disagree are a
            service whose history is one length and whose tests are
            another, and nothing says which is meant.
    """

    uow_factory: UnitOfWorkFactory
    logger: Logger
    audit_logger: AuditLogger
    retention_days: int = 365

    def execute(
        self, context: RequestContext, now: Optional[datetime] = None
    ) -> Tuple[int, int]:
        """
        Fold the days that are over, then sweep what is past retention.

        Args:
            context: Request context, for logging.
            now: Reference time; defaults to the current UTC time.

        Returns:
            A pair of ``(day totals written, raw rows deleted)``.
        """
        log = self._get_logger(self.logger, context)
        moment = now or datetime.now(timezone.utc)
        today = moment.replace(hour=0, minute=0, second=0, microsecond=0)

        with self.uow_factory() as uow:
            folded = uow.security_events.fold_days_before(day=today)
            uow.commit()

        swept = 0
        if self.retention_days > 0:
            cutoff = today - timedelta(days=self.retention_days)
            with self.uow_factory() as uow:
                swept = uow.security_events.delete_before(cutoff)
                uow.commit()

        log.info(
            "Security event history rolled up",
            days_folded=folded,
            rows_deleted=swept,
            retention_days=self.retention_days,
        )
        # Only a run that moved something, for the reason
        # `clean_unverified_accounts` gives -- and here it matters twice
        # over: a record on every scheduled run would be a record among
        # which the one run that removed a year of evidence is invisible.
        if folded or swept:
            audit = self._get_audit_logger(self.audit_logger, context)
            audit.log_security_history_swept(
                days_folded=folded, events_deleted=swept
            )
        return folded, swept

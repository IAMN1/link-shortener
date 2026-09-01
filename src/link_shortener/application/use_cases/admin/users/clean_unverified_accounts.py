from dataclasses import dataclass
from typing import Tuple
from datetime import datetime, timedelta, timezone

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class CleanUnverifiedAccountsUseCase(BaseUseCase):
    """
    Removes registrations nobody ever confirmed, and dead tokens with them.

    Without this an unconfirmed registration holds its address for good:
    the account exists, so registering the address again is refused, and
    nobody can sign in to it because signing in needs a confirmed address.
    That is a way to reserve other people's addresses in bulk, and the
    owners have no recourse -- the service simply tells them the address
    is taken.

    Attributes:
        uow_factory: Factory for Unit of Work instances.
        logger: Application logger.
        audit_logger: Audit logger, where a sweep that removed something
            is recorded. The accounts go for a reason nobody argues with,
            but they go, and an account that ceases to exist is a change
            to who may do what -- which is the rule that decides what
            belongs in that journal.
        unverified_ttl_hours: How long a registration may stay unconfirmed.
    """
    uow_factory: UnitOfWorkFactory
    logger: Logger
    audit_logger: AuditLogger
    unverified_ttl_hours: int

    def execute(self, context: RequestContext) -> Tuple[int, int]:
        """
        Sweep expired registrations and spent confirmations.

        Args:
            context: Request context.

        Returns:
            The accounts deleted and the confirmation tokens deleted with
            them, in that order.
        """
        log = self._get_logger(self.logger, context)
        audit = self._get_audit_logger(self.audit_logger, context)
        cutoff = datetime.now(timezone.utc) - timedelta(
            hours=self.unverified_ttl_hours
        )

        with self.uow_factory() as uow:
            deleted = uow.users.delete_unverified_before(cutoff)
            # Confirmations belonging to those accounts went with them
            # through the foreign key. This clears what is left over
            # elsewhere: tokens that expired unused, and tokens already
            # spent by accounts that are still here.
            tokens = uow.email_verifications.delete_expired()
            uow.commit()

        log.info(
            "Unverified accounts swept",
            accounts_deleted=deleted,
            tokens_deleted=tokens,
        )
        # Only a sweep that removed something. A schedule running over a
        # service with nothing to clean would otherwise write a record
        # every run saying it did nothing, and the records that matter
        # would sit among them.
        if deleted:
            audit.log_unverified_accounts_swept(
                accounts_deleted=deleted, tokens_deleted=tokens
            )
        # Both, because the sweep removes both and the command that runs
        # it announces both -- "registrations nobody confirmed, and dead
        # tokens with them". Returning the accounts alone left a run that
        # cleared seven tokens and no account reporting "Deleted 0
        # unconfirmed accounts", which reads as a run that did nothing.
        return deleted, tokens

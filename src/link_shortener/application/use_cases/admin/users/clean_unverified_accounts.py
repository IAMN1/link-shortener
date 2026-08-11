from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
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
        unverified_ttl_hours: How long a registration may stay unconfirmed.
    """
    uow_factory: Callable[[], UnitOfWork]
    logger: Logger
    unverified_ttl_hours: int

    def execute(self, context: RequestContext) -> int:
        """
        Sweep expired registrations and spent confirmations.

        Args:
            context: Request context.

        Returns:
            Number of accounts deleted.
        """
        log = self._get_logger(self.logger, context)
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
        return deleted

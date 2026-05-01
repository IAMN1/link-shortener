from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.cache.link_cache import LinkCache
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class CleanExpiredLinksUseCase(BaseUseCase):
    """
    Use case: delete links that have 
    not been accessed for a given number of days.
    """

    uow_factory: Callable[[], UnitOfWork]
    cache: LinkCache
    logger: Logger

    def execute(self, days: int, context: RequestContext) -> int:
        """
        Delete old unaccessed links.

        Returns:
            Number of deleted links.
        """
        log = self._get_logger(self.logger, context)
        
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        with self.uow_factory() as uow:
            deleted_codes = uow.links.delete_unaccessed_before(cutoff)

            # invalidate cache
            for code in deleted_codes:
                self.cache.delete(code)

            uow.commit()
        
        log.info("Cleaned expired links", days=days, deleted=len(deleted_codes))
        return len(deleted_codes)

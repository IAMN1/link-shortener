from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.cache.link_cache import LinkCache
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain.repositories.link_repository import LinkRepository


@dataclass
class CleanExpiredLinksUseCase(BaseUseCase):
    """
    Use case: delete links that have 
    not been accessed for a given number of days.
    """

    repository: LinkRepository
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
        deleted_codes = self.repository.delete_unaccessed_before(cutoff)
        
        # invalidate cache
        for code in deleted_codes:
            self.cache.delete(code)
        
        log.info("Cleaned expired links", days=days, deleted=len(deleted_codes))
        return len(deleted_codes)
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.cache.link_cache import LinkCache
from link_shortener.application.ports.cache.link_service_stats_cache import (
    StatsCache,
)
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class CleanExpiredLinksUseCase(BaseUseCase):
    """
    Use case: delete links whose expiry has passed.

    Expiry is the only criterion. Sweeping by ``last_accessed`` instead
    deletes the wrong rows in both directions: a permanent link nobody has
    clicked for a month goes, while a link that has actually expired stays
    on -- and, being found by deduplication, makes its URL impossible to
    shorten again.

    Deleting an expired link removes nothing that was still being served:
    a redirect to it already answers ``410``.

    Attributes:
        uow_factory: Callable factory for creating Unit of Work instances.
        cache: Link cache to invalidate alongside the rows.
        stats_cache: Cache of service-wide totals, dropped when rows go.
        logger: Application logger.
    """

    uow_factory: Callable[[], UnitOfWork]
    cache: LinkCache
    stats_cache: StatsCache
    logger: Logger

    def execute(self, context: RequestContext) -> int:
        """
        Delete every link that has expired.

        Args:
            context: Request context.

        Returns:
            Number of deleted links.
        """
        log = self._get_logger(self.logger, context)

        now = datetime.now(timezone.utc)

        with self.uow_factory() as uow:
            deleted_links = uow.links.delete_expired(now)
            uow.commit()

        # Invalidated after the commit, never before. Until it lands, every
        # other connection still sees the rows, so a read arriving mid-sweep
        # would refill exactly the entries the loop had just dropped -- and
        # nothing would come back for them a second time.
        failed = 0
        for link in deleted_links:
            try:
                if not self.cache.delete(link):
                    failed += 1
            except Exception:
                failed += 1

        if failed:
            # The cache degrades silently by design, which is right on the
            # request path and wrong here: an entry left behind outlives the
            # row it describes and keeps being served for its whole TTL.
            log.warning(
                "Some cache entries outlived the links they describe",
                deleted=len(deleted_links),
                not_invalidated=failed,
            )

        if deleted_links:
            # The totals counted these rows. Dropped once for the sweep
            # rather than once per link: the key is the same one either way.
            self.stats_cache.delete_stats()

        log.info("Cleaned expired links", deleted=len(deleted_links))
        return len(deleted_links)

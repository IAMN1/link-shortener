from dataclasses import dataclass
from typing import Callable

from link_shortener.domain import ShortCode, LinkNotFoundError
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.context import RequestContext
from link_shortener.application.ports.cache.link_cache import LinkCache
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class UpdateLinkStatsUseCase(BaseUseCase):
    """
    Increments the click counter for a link and updates the cache.

    Designed to be called from a Celery worker. It uses its own UoW
    to ensure a fresh transaction.
    """
    uow_factory: Callable[[], UnitOfWork]
    link_cache: LinkCache
    logger: Logger

    def execute(self, short_code_str: ShortCode, context: RequestContext) -> None:
        """
        Increment click count.

        Args:
            short_code_str: Short code string.
            context: Request context (only used for logging).
        """
        log = self._get_logger(self.logger, context)
        log.debug("Background task: updating link stats", short_code=short_code_str)

        try:
            short_code = ShortCode(short_code_str)
        except ValueError as e:
            log.error("Invalid short code format", short_code=short_code_str, error=str(e))
            return

        with self.uow_factory() as uow:
            try:
                updated_link = uow.links.increment_clicks(short_code)
                uow.commit()
            except LinkNotFoundError:
                log.warning("Link not found during stats update")
                return

        # Refresh cache with the latest click count
        self.link_cache.save(updated_link)

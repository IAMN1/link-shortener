from dataclasses import dataclass
from typing import Callable

from link_shortener.domain import ShortCode, LinkNotFoundError
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class UpdateLinkStatsUseCase(BaseUseCase):
    """
    Increments the click counter for a link.

    Designed to be called from a Celery worker. It uses its own UoW
    to ensure a fresh transaction.

    It touches no cache. It used to refresh the cached entity with the new
    click count, and that write -- landing after its transaction closed --
    is what brought deleted links back to life on the redirect path.
    """
    uow_factory: Callable[[], UnitOfWork]
    logger: Logger

    def execute(self, short_code_str: str, context: RequestContext) -> None:
        """
        Increment click count.

        Args:
            short_code_str: Short code as string (from Celery task).
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
                uow.links.increment_clicks(short_code)
                uow.commit()
            except LinkNotFoundError:
                log.warning("Link not found during stats update")
                return

        # The cache is deliberately not refreshed here.
        #
        # This write is the one that resurrected deleted links. It lands
        # after its own transaction closes, so a DELETE that committed and
        # invalidated in between finds nothing left to invalidate -- and the
        # entry reappears behind the deletion, redirecting for the rest of
        # CACHE_LINK_TTL while the API answers 404 for the same code.
        # Reproduced over plain HTTP with no privileges at all: 24 concurrent
        # readers against one delete, roughly one resurrection in ten. With
        # the click task prevented from running, none.
        #
        # Nothing was buying anything with it. The redirect reads only the
        # URL and the expiry, the info endpoints do not read the cache, and
        # the deduplication paths confirm what they find against the
        # database -- so the click count in a cached entity is read by
        # nobody. Warming stays where it belongs: on the redirect's own
        # repository hit.

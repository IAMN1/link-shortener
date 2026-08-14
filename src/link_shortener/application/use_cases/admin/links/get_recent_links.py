from dataclasses import dataclass
from typing import List

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import Link


@dataclass
class GetRecentLinksUseCase(BaseUseCase):
    """
    Use case: retrieve most recently created links.
    """

    uow_factory: UnitOfWorkFactory
    logger: Logger

    def execute(self, limit: int, context: RequestContext) -> List[Link]:
        """
        Return up to `limit` recent links.
        """
        log = self._get_logger(self.logger, context)
        log.debug("Fetching recent links", limit=limit)

        with self.uow_factory(read_only=True) as uow:
            result = uow.links.get_recent(limit)

        return result

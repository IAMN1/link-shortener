from dataclasses import dataclass
from typing import List

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import LinkRepository
from link_shortener.domain.entities.link import Link


@dataclass
class GetRecentLinksUseCase(BaseUseCase):
    """
    Use case: retrieve most recently created links.
    """

    repository: LinkRepository
    logger: Logger

    def execute(self, limit: int, context: RequestContext) -> List[Link]:
        """
        Return up to `limit` recent links.
        """
        log = self._get_logger(self.logger, context)

        log.debug("Fetching recent links", limit=limit)
        return self.repository.get_recent(limit)

from dataclasses import dataclass

from flask.ctx import RequestContext
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.application.use_cases.links.create_short_link import CreateShortLinkUseCase


@dataclass
class SeedDatabaseUseCase(BaseUseCase):
    """
    Use case: populate database with test links.
    """

    create_short_link_use_case: CreateShortLinkUseCase
    logger: Logger

    def execute(self, count: int, context: RequestContext) -> int:
        """
        Create `count` test links.

        Args:
            count: Number of test links to create.
            context: Request context with client metadata.

        Returns:
            Number of successfully created links.
        """
        log = self._get_logger(self.logger, context)

        created = 0
        for i in range(count):
            url = f"https://seed-db.com{i}"
            try:
                self.create_short_link_use_case(url, context)
                created += 1
            except Exception as e:
                log.warning("Failed to create seed link", url=url, error=str(e))
        log.info("Seeded database", requested=count, created=created)
        return created

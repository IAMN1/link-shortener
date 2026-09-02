from dataclasses import dataclass

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.application.use_cases.links.create_short_link import CreateShortLinkUseCase


@dataclass(frozen=True)
class SeedResult:
    """
    Outcome of a seeding run.

    Attributes:
        created: Number of links actually created.
        existing: Number of URLs that already had a link (deduplicated).
    """
    created: int
    existing: int


@dataclass
class SeedDatabaseUseCase(BaseUseCase):
    """
    Use case: populate database with test links.
    """

    create_short_link_use_case: CreateShortLinkUseCase
    logger: Logger

    def execute(self, count: int, context: RequestContext) -> SeedResult:
        """
        Create `count` test links.

        Links that already exist are reported separately rather than
        counted as created: deduplication returns the stored link, and
        counting it as new would overstate the batch.

        The first failure aborts the run, so a rejected request is not
        reported as an empty database.

        Args:
            count: Number of test links to create.
            context: Request context with client metadata.

        Returns:
            SeedResult with the created / already-existing counts.

        Raises:
            Exception: Whatever the create use case raised, after logging
                how far the seeding got.
        """
        log = self._get_logger(self.logger, context)

        created = 0
        existing = 0
        for i in range(count):
            # A path per link, not a host per link: ``seed-db.com{i}``
            # spelled ``seed-db.com0``, ``seed-db.com1``, ... -- a fresh
            # hostname under a top-level domain that does not exist, once
            # per row. They validate and they deduplicate, so the seeding
            # worked; what it produced was not the shape of anything a
            # deployment stores.
            url = f"https://seed-db.example/{i}"
            try:
                response = self.create_short_link_use_case.execute(url, context)
            except Exception as e:
                log.error(
                    "Seeding aborted",
                    url=url,
                    error=str(e),
                    created=created,
                    existing=existing,
                )
                raise

            if response.is_new:
                created += 1
            else:
                existing += 1

        log.info(
            "Seeded database", requested=count, created=created, existing=existing
        )
        return SeedResult(created=created, existing=existing)

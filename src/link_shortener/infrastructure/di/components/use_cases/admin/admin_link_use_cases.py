from dataclasses import dataclass
from typing import Callable

from link_shortener.application import (
    CleanExpiredLinksUseCase,
    GetRecentLinksUseCase,
    SeedDatabaseUseCase,
    CreateShortLinkUseCase,
    LinkCache,
    Logger,
    UnitOfWork,
)


@dataclass
class AdminLinkUseCasesComponent:
    """
    Holds the dependencies needed for administrative link operations
    and exposes factory methods for the corresponding use cases.
    """

    uow_factory: Callable[[], UnitOfWork]
    """Factory to create Unit of Work instances."""

    cache: LinkCache
    """Cache implementation for link data."""

    logger: Logger
    """Application logger injected into the use cases."""

    create_short_link_use_case: CreateShortLinkUseCase
    """Use case needed by ``SeedDatabaseUseCase`` to create test links."""

    def get_clean_expired_links_use_case(self) -> CleanExpiredLinksUseCase:
        """
        Return a fully configured ``CleanExpiredLinksUseCase``.

        The use case deletes links that have not been accessed for a
        specified number of days.
        """
        return CleanExpiredLinksUseCase(
            uow_factory=self.uow_factory,
            cache=self.cache,
            logger=self.logger,
        )

    def get_get_recent_links_use_case(self) -> GetRecentLinksUseCase:
        """
        Return a fully configured ``GetRecentLinksUseCase``.

        Retrieves the most recently created links.
        """
        return GetRecentLinksUseCase(
            uow_factory=self.uow_factory,
            logger=self.logger,
        )

    def get_seed_database_use_case(self) -> SeedDatabaseUseCase:
        """
        Return a fully configured ``SeedDatabaseUseCase``.

        Populates the database with a given number of test links.
        """
        return SeedDatabaseUseCase(
            create_short_link_use_case=self.create_short_link_use_case,
            logger=self.logger,
        )

from dataclasses import dataclass

from link_shortener.application import (
    AuditLogger,
    RollUpVisitsUseCase,
    ServiceCache,
    UnitOfWorkFactory, CleanExpiredLinksUseCase,
    GetRecentLinksUseCase, SeedDatabaseUseCase, CreateShortLinkUseCase,
    Logger
)


@dataclass
class AdminLinkUseCasesComponent:
    """
    Holds the dependencies needed for administrative link operations
    and exposes factory methods for the corresponding use cases.
    """

    uow_factory: UnitOfWorkFactory
    """Factory to create Unit of Work instances."""

    cache: ServiceCache
    """Cache implementation for link data."""

    logger: Logger
    """Application logger injected into the use cases."""

    audit_logger: AuditLogger
    """Security journal, for the sweep that removes links."""

    create_short_link_use_case: CreateShortLinkUseCase
    visit_retention_days: int = 90
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
            stats_cache=self.cache,
            logger=self.logger,
            audit_logger=self.audit_logger,
        )

    def get_roll_up_visits_use_case(self) -> RollUpVisitsUseCase:
        """
        Return a fully configured ``RollUpVisitsUseCase``.

        Folds finished days of visits into day totals and then deletes the
        raw rows past the retention window -- in that order, so the charts
        keep their past.
        """
        return RollUpVisitsUseCase(
            uow_factory=self.uow_factory,
            logger=self.logger,
            retention_days=self.visit_retention_days,
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

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
    """Use case needed by ``SeedDatabaseUseCase`` to create test links."""

    visit_retention_days: int = 90
    """How long raw visit rows are kept, from ``VISIT_RETENTION_DAYS``.

    Read by ``RollUpVisitsUseCase``, which folds finished days and then
    deletes the raw rows behind this many. It was left undocumented
    underneath the docstring belonging to the field above it, which read
    as a use case being an ``int``.
    """

    def get_clean_expired_links_use_case(self) -> CleanExpiredLinksUseCase:
        """
        Return a fully configured ``CleanExpiredLinksUseCase``.

        The use case deletes links whose ``expires_at`` has passed, and
        that is its only criterion -- it takes no day count and never
        looks at ``last_accessed``. Its own docstring says why: "Sweeping
        by ``last_accessed`` instead deletes the wrong rows in both
        directions." A permanent link nobody has opened for a year is not
        swept by it and never was.
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

from dataclasses import dataclass

from link_shortener.application import (
    UnitOfWorkFactory, GetServiceStatsUseCase, GetVisitStatsUseCase,
    GetUserActivityStatsUseCase, StatsCache, Logger
)


@dataclass
class StatsUseCasesComponent:
    """
    Creates the statistics use case with all injected dependencies.

    Delegates to a dedicated cache (``StatsCache``) for service-wide
    aggregated data.
    """

    uow_factory: UnitOfWorkFactory
    cache: StatsCache
    base_url: str
    logger: Logger

    def get_get_service_stats_use_case(self) -> GetServiceStatsUseCase:
        """
        Return a configured ``GetServiceStatsUseCase``.

        The use case attempts to serve statistics from the cache; on miss
        it queries the repository and populates the cache.
        """
        return GetServiceStatsUseCase(
            uow_factory=self.uow_factory,
            base_url=self.base_url,
            cache=self.cache,
            logger=self.logger,
        )

    def get_visit_stats_use_case(self) -> GetVisitStatsUseCase:
        """
        Return a configured ``GetVisitStatsUseCase``.

        Deliberately uncached, unlike the service totals above: the figures
        move with every redirect, and a cached chart that lags by minutes
        is a chart nobody trusts twice.
        """
        return GetVisitStatsUseCase(
            uow_factory=self.uow_factory,
            logger=self.logger,
        )

    def get_user_activity_stats_use_case(self) -> GetUserActivityStatsUseCase:
        return GetUserActivityStatsUseCase(
            uow_factory=self.uow_factory,
            base_url=self.base_url,
        )

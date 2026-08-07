from dataclasses import dataclass
from typing import Callable

from link_shortener.application import (
    GetServiceStatsUseCase,
    GetUserActivityStatsUseCase,
    StatsCache,
    Logger,
    UnitOfWork,
)


@dataclass
class StatsUseCasesComponent:
    """
    Creates the statistics use case with all injected dependencies.

    Delegates to a dedicated cache (``StatsCache``) for service-wide
    aggregated data.
    """

    uow_factory: Callable[[], UnitOfWork]
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
    
    def get_user_activity_stats_use_case(self) -> GetUserActivityStatsUseCase:
        return GetUserActivityStatsUseCase(
            uow_factory=self.uow_factory,
            base_url=self.base_url,
        )

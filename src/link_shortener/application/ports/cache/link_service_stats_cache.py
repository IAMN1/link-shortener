from abc import ABC, abstractmethod
from typing import Optional


class StatsCache(ABC):
    """
    Interface for caching service-wide statistics.

    This cache stores aggregated statistics (e.g., total URLs, total clicks,
    popular links) to avoid recomputing them on every request.
    """

    @abstractmethod
    def get_stats(self) -> Optional[dict]:
        """
        Retrieve cached service statistics.

        Returns:
            Optional[dict]: What ``save_stats`` was handed, which is
            ``ServiceStatsResponse.to_dict()`` -- not the repository's
            ``get_stats``, which returns a ``ServiceLinkStats`` holding
            ``Link`` entities and no average. Or None if nothing is
            cached, or what was cached has expired.
        """
        ...

    @abstractmethod
    def save_stats(self, stats: dict) -> None:
        """
        Store service statistics in the cache with appropriate TTL.

        Args:
            stats (dict): Dictionary of statistics to cache.
        """
        ...

    @abstractmethod
    def delete_stats(self) -> None:
        """
        Invalidate cached statistics (e.g., after a change).
        """
        ...

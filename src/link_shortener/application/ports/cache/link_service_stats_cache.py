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
            Optional[dict]: Dictionary with statistics 
            (format matches repository.get_stats()) or None if not cached/expired.
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

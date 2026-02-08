"""
Экспорт Value Objects
"""

from .cache_strategy import (
    CacheKeyStrategy,
    HashCacheStrategy,
    InfoCacheStrategy,
    RedirectCacheStrategy,
    StatsCacheStrategy,
)
from .short_link_result import (
    BatchLinkData,
    BatchProcessingSummary,
    BatchResultItem,
    LinkInfoResult,
    RedirectResult,
    ServiceStatsResult,
    ShortLinkCreationResult,
)

__all__ = [
    # Стратегии кэширования
    "CacheKeyStrategy",
    "HashCacheStrategy",
    "RedirectCacheStrategy",
    "InfoCacheStrategy",
    "StatsCacheStrategy",
    # Результаты операций с сылкой
    "ShortLinkCreationResult",
    "RedirectResult",
    "LinkInfoResult",
    "BatchLinkData",
    "BatchResultItem",
    "BatchProcessingSummary",
    "ServiceStatsResult",
]

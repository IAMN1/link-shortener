"""
Экспорт Value Objects
"""

from .cache_strategy import (
    CacheKeyStrategy,
    HashCacheStrategy,
    RedirectCacheStrategy,
    InfoCacheStrategy,
    StatsCacheStrategy,
)

from .short_link_result import (
    ShortLinkCreationResult,
    RedirectResult,
    LinkInfoResult,
    BatchLinkData,
    BatchResultItem,
    BatchProcessingSummary,
    ServiceStatsResult
)

__all__ = [
    # Стратегии кэширования
    'CacheKeyStrategy',
    'HashCacheStrategy',
    'RedirectCacheStrategy',
    'InfoCacheStrategy',
    'StatsCacheStrategy',

    # Результаты операций с сылкой
    'ShortLinkCreationResult',
    'RedirectResult',
    'LinkInfoResult',
    'BatchLinkData',
    'BatchResultItem',
    'BatchProcessingSummary',
    'ServiceStatsResult'
]
from .entities.link import Link
from .interfaces.cache.abc_cache import ICacheClient
from .interfaces.database.abc_repository import ILinkRepository
from .interfaces.logger.abc_logger import ILogger
from .interfaces.utils.abc_code_generator import ICodeGenerator
from .interfaces.utils.abc_url_validator import IUrlValidator
from .services.base_service import BaseService
from .services.cache.cache_manager import CacheManager
from .services.link.batch_link_processor import BatchLinkProcessor
from .services.link.link_creator import ShortLinkCreator
from .services.link.link_information import LinkInformation
from .services.link.link_redirector import LinkRedirector
from .services.link.link_statistics import LinkStatistics
from .value_objects.cache_strategy import (
    CacheKeyStrategy,
    HashCacheStrategy,
    InfoCacheStrategy,
    RedirectCacheStrategy,
    StatsCacheStrategy,
)
from .value_objects.short_link_result import (
    BatchLinkData,
    BatchProcessingSummary,
    BatchResultItem,
    LinkInfoResult,
    RedirectResult,
    ServiceStatsResult,
    ShortLinkCreationResult,
)

__all__ = [
    # entities
    "Link",
    # intefaces
    "ICacheClient",
    "ILinkRepository",
    "ILogger",
    "ICodeGenerator",
    "IUrlValidator",
    # services
    "BaseService",
    "CacheManager",
    "BatchLinkProcessor",
    "ShortLinkCreator",
    "LinkInformation",
    "LinkRedirector",
    "LinkStatistics",
    # value object
    "CacheKeyStrategy",
    "HashCacheStrategy",
    "RedirectCacheStrategy",
    "InfoCacheStrategy",
    "StatsCacheStrategy",
    "ShortLinkCreationResult",
    "RedirectResult",
    "LinkInfoResult",
    "BatchLinkData",
    "BatchResultItem",
    "BatchProcessingSummary",
    "ServiceStatsResult",
]

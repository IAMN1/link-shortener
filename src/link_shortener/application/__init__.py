from .dtos.responses import (BatchCreateResponse, BatchItemResponse,
                             ExtendedLinkInfoResponse, ServiceStatsResponse,
                             ShortLinkResponse, StatsItemResponse)
from .ports.cache.link_cache import LinkCache
from .ports.cache.link_service_stats_cache import StatsCache
from .ports.cache.redirect_cache import RedirectCache
from .ports.logger.audit import AuditLogger
from .ports.logger.logger import Logger
from .ports.rate_limiter import RateLimiter
from .ports.task_queue import TaskQueue

from .services.link_service import LinkService

from .use_cases.batch.batch_create_links import BatchCreateLinksUseCase
from .use_cases.batch.creator import BatchLinkCreator
from .use_cases.batch.fetcher import BatchLinkFetcher
from .use_cases.batch.grouper import UrlGrouper
from .use_cases.batch.response_builder import BatchResponseBuilder
from .use_cases.links.create_short_link import CreateShortLinkUseCase
from .use_cases.links.get_link_info import (GetExtendLinkInfoUseCase,
                                      GetLinkInfoUseCase)
from .use_cases.links.redirect_link import RedirectLinkUseCase
from .use_cases.links.delete_link import DeleteLinkUseCase
from .use_cases.links.update_link_stats import UpdateLinkStatsUseCase
from .use_cases.stats.get_service_stats import GetServiceStatsUseCase
from .use_cases.admin.clean_expired_links import CleanExpiredLinksUseCase
from .use_cases.admin.get_recent_links import GetRecentLinksUseCase
from .use_cases.admin.seed_database import SeedDatabaseUseCase

from .context import RequestContext

__all__ = [
    # Dto's
    "ShortLinkResponse",
    "BatchItemResponse",
    "BatchCreateResponse",
    "StatsItemResponse",
    "ServiceStatsResponse",
    "ExtendedLinkInfoResponse",

    # Ports
    "LinkCache",
    "StatsCache",
    "RedirectCache",
    "AuditLogger",
    "Logger",
    "RateLimiter",
    "TaskQueue",

    # Services
    "LinkService",

    # Usecases
    ## batch
    "BatchCreateLinksUseCase",
    "BatchLinkCreator",
    "BatchLinkFetcher",
    "UrlGrouper",
    "BatchResponseBuilder",

    ## links
    "CreateShortLinkUseCase",
    "GetLinkInfoUseCase",
    "GetExtendLinkInfoUseCase",
    "RedirectLinkUseCase",
    "DeleteLinkUseCase",
    "UpdateLinkStatsUseCase",
    
    ## stats 
    "GetServiceStatsUseCase",

    ## admin
    "CleanExpiredLinksUseCase",
    "GetRecentLinksUseCase",
    "SeedDatabaseUseCase",

    # Context
    "RequestContext",
]

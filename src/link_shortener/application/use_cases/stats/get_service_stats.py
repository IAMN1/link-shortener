from dataclasses import dataclass
from datetime import datetime
import time
from typing import Callable



from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.stats import ServiceStatsResponse, StatsItemResponse
from link_shortener.application.ports.cache.link_service_stats_cache import StatsCache
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.application.utils.url_utils import build_short_url


@dataclass
class GetServiceStatsUseCase(BaseUseCase):
    """
    Compute service-wide statistics (total URLs, clicks, top links).

    Attempts to serve from cache; if miss, queries repository, caches the
    result, and returns it. In case of failure, returns an empty statistics
    container to avoid crashing the caller.
    """

    uow_factory: Callable[[], UnitOfWork]
    base_url: str
    cache: StatsCache
    logger: Logger

    def execute(self, context: RequestContext) -> ServiceStatsResponse:
        """
        Get service stats.

        Args:
            context: Request context.

        Returns:
            ServiceStatsResponse, never None.
        """

        log = self._get_logger(self.logger, context)
        start_time = time.perf_counter()
        log.debug("Getting service stats")

        try:
            # 1. Try cache first
            cached_stats = self.cache.get_stats()
            if cached_stats:
                log.info("Stats cache hit")

                # Rehydrate popular links from serialised data
                popular_links = []
                for item in cached_stats["popular_links"]:
                    created_at = datetime.fromisoformat(item["created_at"])
                    popular_links.append(
                        StatsItemResponse(
                            short_code=item["short_code"],
                            short_url=item["short_url"],
                            original_url=item["original_url"],
                            clicks=item["clicks"],
                            created_at=created_at,
                        )
                    )

                return ServiceStatsResponse(
                    total_urls=cached_stats["total_urls"],
                    total_clicks=cached_stats["total_clicks"],
                    avg_clicks_per_url=cached_stats["avg_clicks_per_url"],
                    popular_links=popular_links,
                )

            # 2. Cache miss – query repository read‑only
            with self.uow_factory(read_only=True) as uow:
                stats_data = uow.links.get_stats()

            total_urls = stats_data.get("total_urls", 0)
            total_clicks = stats_data.get("total_clicks", 0)
            avg_clicks = total_clicks / total_urls if total_urls > 0 else 0

            popular_links = stats_data.get("popular_links", [])

            response = ServiceStatsResponse(
                total_urls=total_urls,
                total_clicks=total_clicks,
                avg_clicks_per_url=round(avg_clicks, 2),
                popular_links=[
                    StatsItemResponse(
                        short_code=str(link.short_code.value),
                        short_url=build_short_url(self.base_url, link.short_code.value),
                        original_url=str(link.original_url.value),
                        clicks=link.clicks,
                        created_at=link.created_at,
                    )
                    for link in popular_links
                ],
            )

            # 3. Cache the freshly computed stats
            self.cache.save_stats(response.to_dict())

            log.info(
                "Stats retrieved",
                urls=total_urls,
                clicks=total_clicks,
                avg_clicks=round(avg_clicks, 2),
            )

            return response
        except Exception as e:
            log.exception("Error getting service stats", exc_info=str(e))

            # Fallback: return empty statistics
            return ServiceStatsResponse(
                total_urls=0, total_clicks=0, avg_clicks_per_url=0.0, popular_links=[]
            )
        finally:
            duration = time.perf_counter() - start_time
            log.debug("Execution time", duration_ms=round(duration * 1000, 2))

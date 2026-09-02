from dataclasses import dataclass
from datetime import datetime
import time



from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.stats import ServiceStatsResponse, StatsItemResponse
from link_shortener.application.ports.cache.link_service_stats_cache import StatsCache
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class GetServiceStatsUseCase(BaseUseCase):
    """
    Compute service-wide statistics (total URLs, clicks, top links).

    Attempts to serve from cache; if miss, queries repository, caches the
    result, and returns it. A failure propagates: "I could not count" and
    "there is nothing to count" are different answers, and returning an
    empty container for the first gave the caller a lie it could not detect.
    """

    uow_factory: UnitOfWorkFactory
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

            total_urls = stats_data.total_urls
            total_clicks = stats_data.total_clicks
            avg_clicks = total_clicks / total_urls if total_urls > 0 else 0

            # Its own name: the branch above builds ``popular_links`` out of
            # what the cache kept, and these are the entities the repository
            # returned. One name for both made the two shapes look alike.
            most_clicked = stats_data.popular_links

            response = ServiceStatsResponse(
                total_urls=total_urls,
                total_clicks=total_clicks,
                avg_clicks_per_url=round(avg_clicks, 2),
                # Through the DTO's own factory, which is this and was
                # written for it. Spelled out here instead, the two said
                # the same five lines and only one of them was covered by
                # the tests that build a DTO.
                popular_links=[
                    StatsItemResponse.from_link(link, self.base_url)
                    for link in most_clicked
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
            # Raised on, not swallowed. Answering 200 with
            # ``{0, 0, 0.0, []}`` would say "the service is empty" for any
            # failure at all, which is a lie a caller cannot detect --
            # and it is reachable without touching anything, since
            # DATABASE_STATEMENT_TIMEOUT aborts the aggregate over a large
            # enough table.
            #
            # An error here is not a degraded answer, because there is no
            # fallback source for these numbers. The global handler turns it
            # into a 500, which is what "I could not count" means.
            log.exception("Error getting service stats", error=str(e))
            raise
        finally:
            duration = time.perf_counter() - start_time
            log.debug("Execution time", duration_ms=round(duration * 1000, 2))

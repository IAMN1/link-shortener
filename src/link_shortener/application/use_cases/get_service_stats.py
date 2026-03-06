from dataclasses import dataclass
from datetime import datetime


from link_shortener.application import (
    ServiceStatsResponse, StatsItemResponse, StatsCache, Logger
)
from link_shortener.domain import LinkRepository


@dataclass
class GetServiceStatsUseCase:
    """
    Use case: Retrieve service-wide statistics.

    Steps:
    1. Attempt to get cached statistics.
    2. If cache miss, query repository.
    3. Compute derived metrics (avg clicks per URL).
    4. Cache the result and return.
    """

    repository: LinkRepository
    base_url: str
    cache: StatsCache
    logger: Logger

    def execute(self) -> ServiceStatsResponse:
        """
        Execute the get service stats use case.

        Returns:
            ServiceStatsResponse with aggregated statistics.
        """
        try:
            # 1. Check cache
            cached_stats = self.cache.get_stats()
            if cached_stats:
                self.logger.info("Stats cache hit")

                # Rehydrate popular_links from serialized data
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

            # 2. Cache miss – query repository
            stats_data = self.repository.get_stats()

            # 3. Build response
            total_urls = stats_data.get("total_urls", 0)
            total_clicks = stats_data.get("total_clicks", 0)
            avg_clicks = total_clicks / total_urls if total_urls > 0 else 0

            popular_links = stats_data.get("popular_links", [])[:10]

            response = ServiceStatsResponse(
                total_urls=total_urls,
                total_clicks=total_clicks,
                avg_clicks_per_url=round(avg_clicks, 2),
                popular_links=[
                    StatsItemResponse(
                        short_code=str(link.short_code.value),
                        short_url=f"{self.base_url.rstrip('/')}/{link.short_code.value}",
                        original_url=str(link.original_url.value),
                        clicks=link.clicks,
                        created_at=link.created_at,
                    )
                    for link in popular_links
                ],
            )

            # 4. Cache the result
            self.cache.save_stats(response.to_dict())

            self.logger.info(
                "Stats retrieved",
                urls=total_urls,
                clicks=total_clicks,
                avg_clicks=round(avg_clicks, 2),
            )

            return response
        except Exception as e:
            self.logger.exception("Error getting service stats", exc_info=str(e))

            # Возвращение пустой статистики в случае ошибки
            return ServiceStatsResponse(
                total_urls=0, total_clicks=0, avg_clicks_per_url=0.0, popular_links=[]
            )

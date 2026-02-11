from dataclasses import dataclass
from typing import Optional

from ..dtos.responses import ServiceStatsResponse

from ..ports.cache.link_service_stats_cache import StatsCache
from ..ports.logger.logger import Logger
from domain.repositories.link_repository import LinkRepository


@dataclass
class GetServiceStatsUseCase:
    """
    Use case: Получения статистики сервиса
    """
    repository: LinkRepository
    cache: StatsCache
    logger: Optional[Logger]
    cache_ttl: int = 300

    def execute(self) -> ServiceStatsResponse:
        """
        Основной сценарий использования.
        
        Returns:
            ServiceStatsResponse: Статистика сервиса
        """
        try:
            # 1. Попытка получения данных из кэша
            cached_stats = self.cache.get_stats()
            if cached_stats:
                if self.logger:
                    self.logger.info("Stats cache hit")
                    return ServiceStatsResponse(**cached_stats)
            
            # 2. получение из репозитория
            stats_data = self.repository.get_stats()

            # 3. формирование ответа
            total_urls = stats_data.get('total_urls', 0)
            total_clicks = stats_data.get('total_clicks', 0)
            avg_clicks = total_clicks / total_urls if total_urls > 0 else 0
            
            popular_links = stats_data.get('popular_links', [])

            response = ServiceStatsResponse(
                total_urls=total_urls,
                total_clicks=total_clicks,
                avg_clicks_per_url=round(avg_clicks, 2),
                popular_links=[
                    {
                        'short_code': str(link.short_code),
                        'original_url': str(link.original_url),
                        'clicks': link.clicks,
                        'created_at': link.created_at
                    }
                    for link in popular_links[:10]
                ]
            )

            # 4. кэширование результата
            self.cache.save_stats(response.dict())

            if self.logger:
                self.logger.info(
                    'Stats retrieved',
                    urls=total_urls,
                    clicks=total_clicks,
                    avg_clicks=round(avg_clicks, 2)
                )
            
            return response
        except Exception as e:
            if self.logger:
                self.logger.exception('Error getting service stats', exc_info=str(e))
            
            # Возвращение пустой статистики в случае ошибки
            return ServiceStatsResponse(
                total_urls=0,
                total_clicks=0,
                avg_clicks_per_url=0.0,
                popular_links=[]
            )
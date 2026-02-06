from typing import Any, Dict, List, Optional

from src.link_shortener.domain.entities.link import Link

from ..cache.cache_manager import CacheManager
from ..base_service import BaseService
from ...interfaces.database.abc_repository import ILinkRepository
from ...interfaces.logger.abc_logger import ILogger
from ...value_objects.short_link_result import ServiceStatsResult
from ...value_objects.cache_strategy import StatsCacheStrategy


class LinkStatistics(BaseService):
    """Доменный сервис для получения статистики о ссылке"""

    def __init__(
        self,
        repository: ILinkRepository,
        cache_manager: Optional[CacheManager] = None,
        stats_strategy: Optional[StatsCacheStrategy] = None,
        cache_ttl: int = 300,
        logger: Optional[ILogger] = None,
        popular_limit: int = 10
    ):
        super().__init__(logger)
        self._repository = repository
        self._cache_manager = cache_manager
        self._stats_strategy = stats_strategy
        self._cache_ttl = cache_ttl
        self._popular_limit = popular_limit
    
    def get_service_stats(self) -> ServiceStatsResult:
        """
        Получение статистики сервиса

        Returns:
            ServiceStatsResult: Статистика сервиса
        """
        self._log_debug('Запрос сатистики сервиса')

        # 1. Проверка кэша
        if self._cache_manager and self._stats_strategy:
            cached_stats = self._cache_manager.get_service_stats()

            if cached_stats:
                 self._log_debug('Статистика найдена в кэше')
                 return ServiceStatsResult(**cached_stats)
        
        # 2. получение статистики из репозитория
        stats = self._repository.get_stats()

        # 3. Форматирование статистики
        total_urls = stats.get('total_urls', 0)
        total_clicks = stats.get('total_clicks', 0)
        avg_clicks = round((total_clicks / total_urls if total_urls else 0), 2)
        popular_urls = stats.get('popular_urls', [])

        # 4. Форматирование популярных ссылок
        formatted_popular_urls = self._format_popular_urls(popular_urls)
        
        result = ServiceStatsResult(
             total_urls=total_urls,
             total_clicks=total_clicks,
             avg_clicks_per_url=avg_clicks,
             popular_urls=formatted_popular_urls
        )

        # 5. Кэширование статистики
        if self._cache_manager and self._stats_strategy:
            success = self._cache_manager.cache_service_stats(result, self._stats_strategy, self._cache_ttl)
            if success:
                self._log_debug('Статистика успешно закэширована')
        
        self.info('Статистика получена', total_urls=total_urls, total_clicks=total_clicks)
        
        return result

    def _format_popular_urls(self, popular_urls: list[Link]) -> List[Dict[str, Any]]:
        """Форматирование популярных ссылок"""
        
        formatted_urls = []

        for link in popular_urls[:self._popular_limit]:
            formatted_urls.append({
                'short_code': link.short_code,
                'original_url': (
                    link.original_url[:50] + '...'
                    if len(link.original_url) > 100
                    else link.original_url
                ),
                'clicks': link.clicks,
                'created_at': link.created_at.isoformat(),
                'last_accessed': (
                    link.last_accessed.isoformat()
                    if link.last_accessed else None
                )
            })
        
        return formatted_urls

    def service_stats_with_details(self, base_url: str, include_details: bool = False) -> Dict[str, Any]:
        """
        Получение расширенной статистики сервиса.
        Используется на уровне приложения.

        Args:
            base_url (str): Базовый Url для формированя сокращенной ссылки
            include_details (bool, optional): флаг включения детальной статистики. Defaults to False.

        Returns:
            Dict[str, Any]: расширенная статистика сервиса
        """

        stats = self.get_service_stats()
        result = {
            'total_urls': stats.total_urls,
            'total_clicks': stats.total_clicks,
            'avg_clicks_per_url': stats.avg_clicks_per_url,
            'popular_urls': []
        }
        #  добавление short_url к популярным ссылкам
        for url_info in stats.popular_urls:
            url_with_short = dict(url_info)
            url_with_short['short_url'] = f'{base_url.rstrip('/')}/{url_info['short_code']}'

            result['popular_urls'].append(url_with_short)
        
        # Дополнительная детализация если флаг включен
        if include_details:
            result['cache_hit_rate'] = self._get_cache_hit_rate()
            result['service_uptime'] = self._get_service_uptime()
        
        return result
    
    def _get_cache_hit_rate(self) -> Optional[float]:
        """Получение показателя попаданий в кэш"""
        if self._cache_manager:
            stats = self._cache_manager.get_cache_stats()
            if isinstance(stats, dict) and 'hit_rate' in stats:
                return stats['hit_rate']
        return None
    
    def _get_service_uptime(self) -> Optional[int]:
        """Получение времени работы сервиса (в секундах)"""
        # TODO ДОПИСАТЬ И ВЫНЕСТИ В ОТДЕЛЬНЫЙ СЕРВИС
        return None
        
        
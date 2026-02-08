from datetime import datetime
from unittest.mock import Mock
import pytest

from src.link_shortener.domain.entities.link import Link
from src.link_shortener.domain.services.link.link_statistics import LinkStatistics
from src.link_shortener.domain.value_objects.cache_strategy import StatsCacheStrategy
from src.link_shortener.domain.value_objects.short_link_result import ServiceStatsResult


@pytest.mark.unit
class TestLinkStatistics:
    """Тесты для LinkStatistics"""

    @pytest.fixture
    def stats_service(self, mock_repository, mock_logger, mock_cache_manager):
        """Фикстура сервиса LinkStatistics"""
        return LinkStatistics(
            repository=mock_repository,
            cache_manager=mock_cache_manager,
            stats_strategy=StatsCacheStrategy(),
            logger=mock_logger,
            cache_ttl=300,
            popular_limit=5
        )
    
    @pytest.fixture
    def sample_popular_links(self):
        """Тестовые популярные ссылки"""
        links = []
        for i in range(10):
            link = Link.create(
                url_hash=f'hash_{i}',
                short_code=f'code_{i}',
                original_url=f'https://example{i}.com/path/{i}'
            )
            link.clicks = 100 - i * 20  # 100, 80, 60, 40, 20
            link.last_accessed = datetime(2026, 2, 7, 12, i, 0)
            links.append(link)
        return links
    
    def test_get_service_stats_from_cache(self, stats_service, mock_cache_manager):
        """Тест получения статистики из кэша"""
        cached_stats = {
            'total_urls': 100,
            'total_clicks': 1000,
            'avg_clicks_per_url': 10.0,
            'popular_urls': []
        }
        mock_cache_manager.get_service_stats.return_value = cached_stats

        # Act
        result = stats_service.get_service_stats()

        # Assert
        assert isinstance(result, ServiceStatsResult)
        assert result.total_urls == 100
        assert result.total_clicks == 1000
        assert result.avg_clicks_per_url == 10.0
        mock_cache_manager.get_service_stats.assert_called_once()
    
    def test_get_service_stats_from_database(self, stats_service, mock_cache_manager, mock_repository, sample_popular_links):
        """Тест получения статистики из кэша"""
        mock_cache_manager.get_service_stats.return_value = None
        mock_repository.get_stats.return_value = {
            'total_urls': 50,
            'total_clicks': 500,
            'popular_urls': sample_popular_links
        }

        # Act
        result = stats_service.get_service_stats()

        # Assert
        assert isinstance(result, ServiceStatsResult)
        assert result.total_urls == 50
        assert result.total_clicks == 500
        assert result.avg_clicks_per_url == 10.0
        assert len(result.popular_urls) == 5 # выставлено ограничение в 5 (10 - default)
        
        mock_repository.get_stats.assert_called_once()
        mock_cache_manager.cache_service_stats.assert_called_once()
    
    def test_format_popular_urls_with_limit(self, stats_service, sample_popular_links):
        """Тест форматирования популярных ссылок с лимитом"""
        # Act
        formatted = stats_service._format_popular_urls(sample_popular_links)
        
        # Assert
        assert len(formatted) == 5  # Ограничено popular_limit=5 (def 10)
        assert formatted[0]['short_code'] == 'code_0'
        assert formatted[0]['clicks'] == 100
        assert formatted[2]['short_code'] == 'code_2'
        assert formatted[2]['clicks'] == 60
    
    def test_format_popular_urls_short_url(self, stats_service):
        """Тест форматирования не длинных URL"""
        short_link = Link.create(
            url_hash='short_hash',
            short_code='short',
            original_url='https://short.com'
        )
        short_link.clicks = 50
        
        # Act
        formatted = stats_service._format_popular_urls([short_link])
        
        # Assert
        assert formatted[0]['original_url'] == 'https://short.com'  # Не обрезано
        assert '...' not in formatted[0]['original_url']
    
    def test_service_stats_with_details(self, stats_service):
        """Тест получения расширенной статистики"""
        # Arrange
        stats_service.get_service_stats = Mock()
        stats_service.get_service_stats.return_value = ServiceStatsResult(
            total_urls=100,
            total_clicks=1000,
            avg_clicks_per_url=10.0,
            popular_urls=[
                {
                    'short_code': 'code1',
                    'original_url': 'https://test1.com',
                    'clicks': 100,
                    'created_at': '2026-02-07T12:00:00',
                    'last_accessed': '2026-02-08T12:00:00'
                }
            ]
        )
        stats_service._get_cache_hit_rate = Mock(return_value=0.85)
        stats_service._get_service_uptime = Mock(return_value=86400)
        
        # Act
        result = stats_service.service_stats_with_details(
            base_url='https://short.ly',
            include_details=True
        )
        
        # Assert
        assert result['total_urls'] == 100
        assert result['total_clicks'] == 1000
        assert result['avg_clicks_per_url'] == 10.0
        
        # Проверяем добавление short_url
        assert result['popular_urls'][0]['short_url'] == 'https://short.ly/code1'
        
        # Проверяем детализацию
        assert result['cache_hit_rate'] == 0.85
        assert result['service_uptime'] == 86400
    
    def test_service_stats_without_details(self, stats_service):
        """Тест получения статистики без деталей"""
        # Arrange
        stats_service.get_service_stats = Mock()
        stats_service.get_service_stats.return_value = ServiceStatsResult(
            total_urls=100,
            total_clicks=1000,
            avg_clicks_per_url=10.0,
            popular_urls=[]
        )
        
        # Act
        result = stats_service.service_stats_with_details(
            base_url='https://short.ly',
            include_details=False
        )
        
        # Assert
        assert 'cache_hit_rate' not in result
        assert 'service_uptime' not in result
    
    def test_get_cache_hit_rate_with_stats(self, stats_service, mock_cache_manager):
        """Тест получения показателя попаданий в кэш"""
        # Arrange
        mock_cache_manager.get_cache_stats.return_value = {
            'hit_rate': 0.75,
            'miss_rate': 0.25
        }
        
        # Act
        hit_rate = stats_service._get_cache_hit_rate()
        
        # Assert
        assert hit_rate == 0.75
        mock_cache_manager.get_cache_stats.assert_called_once()
    
    def test_get_cache_hit_rate_without_stats(self, stats_service, mock_cache_manager):
        """Тест получения показателя попаданий, когда статистики нет"""
        # Arrange
        mock_cache_manager.get_cache_stats.return_value = None
        
        # Act
        hit_rate = stats_service._get_cache_hit_rate()
        
        # Assert
        assert hit_rate is None
    
    def test_get_cache_hit_rate_without_cache_manager(self, mock_repository, mock_logger):
        """Тест получения показателя попаданий без менеджера кэша"""
        # Arrange
        stats_service = LinkStatistics(
            repository=mock_repository,
            cache_manager=None,
            logger=mock_logger
        )
        
        # Act
        hit_rate = stats_service._get_cache_hit_rate()
        
        # Assert
        assert hit_rate is None
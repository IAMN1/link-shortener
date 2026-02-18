from datetime import datetime
from link_shortener.application.dtos.responses import ServiceStatsResponse
from link_shortener.application.use_cases.get_service_stats import GetServiceStatsUseCase
from link_shortener.domain.entities.link import Link
from link_shortener.domain.value_objects.url_hash import UrlHash
from link_shortener.domain.value_objects.short_code import ShortCode
import pytest


@pytest.fixture
def use_case(
   mock_link_repository,
    mock_stats_cache,
    mock_logger,
    base_url
) -> GetServiceStatsUseCase:
    """Fixture for GetServiceStatsUseCase."""
    
    return GetServiceStatsUseCase(
        repository=mock_link_repository,
        base_url=base_url,
        cache=mock_stats_cache,
        logger=mock_logger,
        cache_ttl=300
    )

@pytest.fixture
def popular_links(valid_original_url):
    """Fixture for a list of popular links."""

    links = []
    for i in range(3):
        url_hash = UrlHash(f'{i:064x}')
        short_code = ShortCode(f'abc12{i}')
        link = Link.create(
            url_hash=url_hash,
            short_code=short_code,
            original_url=valid_original_url
        )
        link.clicks = 100 - i * 10
        links.append(link)
    return links


# ------------------------------------------------------------------
# TestGetServiceStatsUseCase
# ------------------------------------------------------------------
class TestGetServiceStatsUseCase:
    """Tests for GetServiceStatsUseCase."""

    def test_cache_hit(
        self, use_case, mock_stats_cache, mock_link_repository, base_url
    ):
        """Should return stats from cache when present."""
        
        # Arrange
        cached_data = {
            'total_urls': 100,
            'total_clicks': 500,
            'avg_clicks_per_url': 5.0,
            'popular_links': [
                {
                    'short_code': 'abc123',
                    'short_url': f'{base_url}/abc123',
                    'original_url': 'https://test.com',
                    'clicks': 50,
                    'created_at': datetime.now().isoformat()
                }
            ]
        }
        mock_stats_cache.get_stats.return_value = cached_data

        # Act
        response = use_case.execute()

        assert isinstance(response, ServiceStatsResponse)
        assert response.total_urls == 100
        assert response.total_clicks == 500
        assert response.avg_clicks_per_url == 5.0
        assert len(response.popular_links) == 1
        mock_link_repository.get_stats.assert_not_called()
    
    def test_cache_miss_fetch_from_repo(
        self, use_case, mock_stats_cache, mock_link_repository, popular_links
    ):
        """Should fetch stats from repository on cache miss and cache them."""
        
        # Arrange
        mock_stats_cache.get_stats.return_value = None
        repo_stats = {
            'total_urls': 10,
            'total_clicks': 200,
            'popular_links': popular_links
        }
        mock_link_repository.get_stats.return_value = repo_stats

        # Act
        response = use_case.execute()

        # Assert
        assert isinstance(response, ServiceStatsResponse)
        assert response.total_urls == 10
        assert response.total_clicks == 200
        assert response.avg_clicks_per_url == 20.0  # 200/10
        assert len(response.popular_links) == len(popular_links)
        mock_stats_cache.save_stats.assert_called_once()
        # проверка, что сохранили правильные данные
        saved_dict = mock_stats_cache.save_stats.call_args[0][0]
        assert saved_dict['total_urls'] == 10
        assert saved_dict['total_clicks'] == 200
    
    def test_repository_returns_empty(
        self, use_case, mock_stats_cache, mock_link_repository
    ):
        """Should handle empty stats from repository."""

        mock_stats_cache.get_stats.return_value = None
        mock_link_repository.get_stats.return_value = {
            'total_urls': 0,
            'total_clicks': 0,
            'popular_links': []
        }

        # Act
        response = use_case.execute()

        # Assert
        assert response.total_urls == 0
        assert response.total_clicks == 0
        assert response.avg_clicks_per_url == 0.0
        assert response.popular_links == []
    
    def test_repository_raises_exception(
        self, use_case, mock_stats_cache, mock_link_repository
    ):
        """Should return empty stats and log error when repository raises exception."""
        
        mock_stats_cache.get_stats.return_value = None
        mock_link_repository.get_stats.side_effect = Exception("DB error")

        response = use_case.execute()

        assert response.total_urls == 0
        assert response.total_clicks == 0
        assert response.avg_clicks_per_url == 0.0
        assert response.popular_links == []
        use_case.logger.exception.assert_called_once()

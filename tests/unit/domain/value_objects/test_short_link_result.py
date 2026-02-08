from datetime import datetime
import pytest

from src.link_shortener.domain.entities.link import Link
from src.link_shortener.domain.value_objects.short_link_result import BatchLinkData, BatchProcessingSummary, BatchResultItem, LinkInfoResult, RedirectResult, ServiceStatsResult, ShortLinkCreationResult


@pytest.mark.unit
class TestShortLinkResultValueObjects:
    """Тесты для value objects результатов"""

    def test_short_link_creation_result_creation(self):
        """Тест создания ShortLinkCreationResult"""

        link = Link.create(
            url_hash='hash123',
            short_code='code123',
            original_url='https://example.com'
        )

        # Act
        result = ShortLinkCreationResult(
            link=link,
            is_new=True,
            from_cache=False
        )

        # Assert
        assert result.link == link
        assert result.is_new is True
        assert result.from_cache is False
    
    def test_redirect_result_creation(self):
        """тест создания RedirectResult"""
        
        # Act
        result = RedirectResult(
            original_url="https://example.com",
            from_cache=True,
            clicks=100
        )
        
        # Assert
        assert result.original_url == "https://example.com"
        assert result.from_cache is True
        assert result.clicks == 100
    
    def test_link_info_result_creation(self):
        """Тест создания LinkInfoResult"""

        # Act
        result = LinkInfoResult(
            id='id123',
            url_hash='hash123',
            short_code='code123',
            original_url='https://example.com',
            clicks=100,
            created_at=datetime(2026, 2, 7, 1, 48, 0).isoformat(),
            last_accessed=datetime(2026, 2, 8, 1, 50, 0).isoformat(),
        )

        # Assert
        assert result.id == 'id123'
        assert result.url_hash == 'hash123'
        assert result.short_code == 'code123'
        assert result.original_url == 'https://example.com'
        assert result.clicks == 100
        assert result.created_at == '2026-02-07T01:48:00'
        assert result.last_accessed == '2026-02-08T01:50:00'
    
    def test_batch_link_data_creation(self):
        """
        Тест создания BatchLinkData вспомогательной
          структуры для пакетной обработки
        """

        # Act
        data = BatchLinkData(
            url="https://example.com",
            url_hash="hash123",
            short_code="code123",
            clicks=10
        )
        
        # Assert
        assert data.url == "https://example.com"
        assert data.url_hash == "hash123"
        assert data.short_code == "code123"
        assert data.clicks == 10

    def test_batch_result_item_creation(self):
        """Тест создания BatchResultItem результата пакетной обработки"""

        batch_data = BatchLinkData(url='https://example.com')

        # Act
        item = BatchResultItem(
            success=True,
            data=batch_data,
            error=None,
            is_new=True,
            from_cache=False
        )

        # Assert
        assert item.success is True
        assert item.data == batch_data
        assert item.error is None
        assert item.is_new is True
        assert item.from_cache is False
    
    def test_batch_processing_summmary_creation(self):
        """Тест создания BatchProcessingSummary - сводки пакетной обработки"""

        # Act
        summary = BatchProcessingSummary(
            total=100,
            successful=90,
            failed=10,
            new=80,
            existing=10,
            from_cache=5
        )

        # Assert
        assert summary.total == 100
        assert summary.successful == 90
        assert summary.failed == 10
        assert summary.new == 80
        assert summary.existing == 10
        assert summary.from_cache == 5
    
    def test_service_stats_result_creation(self):
        """Тест создания ServiceStatsResult - для статистики сервиса"""
        popular_urls = [
            {'short_code': 'code1', 'original_url': 'https://test1.com', 'clicks': 0},
            {'short_code': 'code2', 'original_url': 'https://test2.com', 'clicks': 10}
        ]

        # Act
        stats = ServiceStatsResult(
            total_urls=1_000,
            total_clicks=10_000,
            avg_clicks_per_url=10.0,
            popular_urls=popular_urls
        )

        # Assert
        assert stats.total_urls == 1_000
        assert stats.total_clicks == 10_000
        assert stats.avg_clicks_per_url == 10.0
        assert len(stats.popular_urls) == 2
        assert stats.popular_urls[0]['short_code'] == 'code1'
        assert stats.popular_urls[1]['short_code'] == 'code2'
        assert stats.popular_urls[0]['clicks'] == 0
        assert stats.popular_urls[1]['clicks'] == 10
    
    def test_value_objects_are_immutable(self):
        """
        Тест неизменяемости value objects
        ShortLinkCreationResult - dataclass(frozen=true) - изменение должно вызвать ошибку
        """
        link = Link.create(
            url_hash='hash1',
            short_code='code1',
            original_url='https://test.com'
        )
        result = ShortLinkCreationResult(
            link=link,
            is_new=True,
            from_cache=False
        )

        # Act & Assert
        with pytest.raises(Exception):
            result.is_new = False

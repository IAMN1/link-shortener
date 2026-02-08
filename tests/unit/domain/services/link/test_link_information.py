from datetime import datetime
from unittest.mock import Mock
import pytest

from src.link_shortener.domain.exceptions import LinkNotFoundError
from src.link_shortener.domain.services.link.link_information import LinkInformation
from src.link_shortener.domain.value_objects.cache_strategy import InfoCacheStrategy
from src.link_shortener.domain.value_objects.short_link_result import LinkInfoResult


@pytest.mark.unit
class TestLinkInformation:
    """Тесты для LinkInformation сервиса"""

    @pytest.fixture
    def link_info_service(self, mock_repository, mock_logger, mock_cache_manager, mock_short_code_extractor):
        """Фикстура сервиса информации о ссылке"""
        return LinkInformation(
            short_code_extractor=mock_short_code_extractor,
            repository=mock_repository,
            cache_manager=mock_cache_manager,
            info_strategy=InfoCacheStrategy(),
            cache_ttl=300,
            logger=mock_logger
        )
    
    @pytest.fixture
    def link_info_service_without_cache(self, mock_repository, mock_logger, mock_short_code_extractor):
        """Фисктура сервиса информации о ссылке без менеджера кэша"""
        return LinkInformation(
            short_code_extractor=mock_short_code_extractor,
            repository=mock_repository,
            cache_manager=None,
            info_strategy=InfoCacheStrategy(),
            logger=mock_logger
        )

    def test_get_link_info_reutrns_with_cache_hit(self, sample_link, link_info_service, mock_cache_manager):
        """тест получения информации о ссылке из кэша"""
        link_code = sample_link.short_code
        link_url = sample_link.original_url
        link_clicks = sample_link.clicks

        mock_cache_manager.get_link_info.return_value = sample_link

        # Act
        result = link_info_service.get_link_info(link_code)

        # Assert
        assert isinstance(result, LinkInfoResult)
        assert result.short_code == link_code
        assert result.original_url == link_url
        assert result.clicks == link_clicks
        mock_cache_manager.get_link_info.assert_called_once()
    
    def test_get_link_info_cache_deserialization_error(self, sample_link, link_info_service, mock_cache_manager, mock_repository, mock_logger):
        """Тест ошибки десериализации из кэша"""
        link_code = sample_link.short_code

        # некоректные данные в кэше
        invalid_cache_data = {'invalid': 'data'}
        mock_cache_manager.get_link_info.return_value = invalid_cache_data

        mock_repository.get_by_short_code.return_value = sample_link

        # Act
        result = link_info_service.get_link_info(link_code)

        # Assert
        # Должен вернуть данные из бд несмотря на ошибку кэша
        assert isinstance(result, LinkInfoResult)
        assert result.short_code == link_code
        mock_logger.error.assert_called_once()
        assert "Ошибка десериализации" in mock_logger.error.call_args[0][0]

    def test_get_link_info_returns_from_database(self, sample_link, link_info_service, mock_repository, mock_cache_manager):
        """тест получения информации о ссылке из репозитория"""
        link_code = sample_link.short_code
        mock_cache_manager.get_link_info.return_value = None
        mock_repository.get_by_short_code.return_value = sample_link

        # Act
        result = link_info_service.get_link_info(link_code)

        # Assert
        mock_cache_manager.get_link_info.assert_called_once()
        mock_repository.get_by_short_code.assert_called_once()
        assert isinstance(result, LinkInfoResult)
        assert result.short_code == link_code
        assert result.clicks == 0
        assert result.created_at == sample_link.created_at.isoformat()
        assert result.last_accessed is None

        # Должен закэшировать результат
        mock_cache_manager.cache_link.assert_called_once()
        call_args = link_info_service._cache_manager.cache_link.call_args
        assert call_args[0][0] == sample_link  # Первый аргумент - ссылка
        assert 'info' in call_args[0][1]  # Стратегия info
    
    def test_get_link_info_not_found(self, link_info_service, mock_cache_manager, mock_repository):
        """Тест получения информации о несуществующей ссылки"""
        mock_cache_manager.get_link_info.return_value = None
        mock_repository.get_by_short_code.return_value = None

        # Act & Assert
        with pytest.raises(LinkNotFoundError) as exc_info:
            link_info_service.get_link_info('non_exist_url')
        
        assert 'не найдена' in str(exc_info.value)
    
    def test_get_link_info_returns_without_cache_manager(self, sample_link, link_info_service_without_cache, mock_repository):
        """Тест работы с без менеджера кэша"""
        link_code = sample_link.short_code

        mock_repository.get_by_short_code.return_value = sample_link

        # Act
        result = link_info_service_without_cache.get_link_info(link_code)

        # Assert
        assert result.short_code == link_code
        mock_repository.get_by_short_code.assert_called_once_with(link_code)
    
    def test_get_link_info_result_conversion(self, sample_link, link_info_service):
        """Тест конвератции Link в LinkInfoResult"""
        link_hash = sample_link.url_hash
        link_code = sample_link.short_code
        sample_link.clicks = 50
        sample_link.last_accessed = datetime(2026, 2, 7, 19, 55, 0)

        # Act
        result = link_info_service._link_to_info_result(sample_link)

        # Assert
        assert isinstance(result, LinkInfoResult)
        assert result.url_hash == link_hash
        assert result.short_code == link_code
        assert result.clicks == 50
        assert result.created_at == sample_link.created_at.isoformat()
        assert result.last_accessed == sample_link.last_accessed.isoformat()

    def test_link_to_info_result_without_last_accessed(self, sample_link, link_info_service):
        """Тест конвертации Link без last_accessed"""
        # Arrange
        

        sample_link
        sample_link.last_accessed = None
        
        # Act
        result = link_info_service._link_to_info_result(sample_link)
        
        # Assert
        assert result.last_accessed is None
    
    def test_get_link_info_with_cache_returns_api_format(self, sample_link, link_info_service):
        """Тест получения информации в формате API"""
        # Arrange
        base_link = 'https://short.ly'
        code = sample_link.short_code
        sample_link.clicks = 30
        
        # Mock get_link_info чтобы вернуть LinkInfoResult
        link_info_result = LinkInfoResult(
            id=sample_link.id,
            url_hash=sample_link.url_hash,
            short_code=sample_link.short_code,
            original_url=sample_link.original_url,
            clicks=sample_link.clicks,
            created_at=sample_link.created_at,
            last_accessed=sample_link.last_accessed
        )
        link_info_service.get_link_info = Mock(return_value=link_info_result)
        
        # Act
        result = link_info_service.get_link_info_with_cache(sample_link.short_code, base_link)
        
        # Assert
        assert result['short_code'] == sample_link.short_code
        assert result['short_url'] == f'{base_link}/{code}'
        assert result['original_url'] == sample_link.original_url
        assert result['clicks'] == sample_link.clicks
        assert result['created_at'] == sample_link.created_at
        assert result['last_accessed'] is None
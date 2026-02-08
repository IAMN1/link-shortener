from datetime import datetime
import pytest

from src.link_shortener.domain.entities.link import Link
from src.link_shortener.domain.exceptions import LinkNotFoundError, ValidationError
from src.link_shortener.domain.services.link.link_redirector import LinkRedirector
from src.link_shortener.domain.value_objects.cache_strategy import HashCacheStrategy, InfoCacheStrategy, RedirectCacheStrategy
from src.link_shortener.domain.value_objects.short_link_result import RedirectResult


@pytest.mark.unit
class TestLinkRedirector:
    """Тесты для LinkRedirector"""

    @pytest.fixture
    def redirector(self, mock_repository, mock_cache_manager, mock_logger, mock_short_code_extractor):
        """Фикстура для LinkRedirector"""
        return LinkRedirector(
            short_code_extractor=mock_short_code_extractor,
            repository=mock_repository,
            cache_manager=mock_cache_manager,
            redirect_strategy=RedirectCacheStrategy(),
            hash_strategy=HashCacheStrategy(),
            info_strategy=InfoCacheStrategy(),
            cache_ttl=3600,
            logger=mock_logger
        )

    @pytest.fixture
    def redirector_without_cache(self, mock_repository, mock_logger, mock_short_code_extractor):
        """Фикстура для LinkRedirector без менеджера кэша"""
        return LinkRedirector(
            short_code_extractor=mock_short_code_extractor,
            repository=mock_repository,
            cache_manager=None,
            redirect_strategy=RedirectCacheStrategy(),
            hash_strategy=HashCacheStrategy(),
            info_strategy=InfoCacheStrategy(),
            cache_ttl=3600,
            logger=mock_logger
        )

    @pytest.fixture
    def sample_redirect_link(self, sample_link) -> Link:
        """Тестовая ссылка для редиректа"""
        sample_link.clicks = 5
        sample_link.last_accessed = datetime(2026, 2, 7, 12, 0, 0)
        return sample_link

    def test_extract_short_code_access(self, sample_redirect_link, redirector, mock_short_code_extractor):
        """Тест успешного извлечения короткого кода"""
        link_code = sample_redirect_link.short_code
        url = sample_redirect_link.original_url
        
        mock_short_code_extractor.extract_code_from_url.return_value = link_code

        # Act
        result = redirector.extract_short_code(url)

        assert result == link_code

        mock_short_code_extractor.validate_short_url_format.assert_called_once_with(url)
        mock_short_code_extractor.extract_code_from_url.assert_called_once_with(url)

    def test_extract_short_code_invalid_format(self, redirector, mock_short_code_extractor):
        """Тест извлечения кода из невалидной ссылки"""
        # Arrange
        mock_short_code_extractor.validate_short_url_format.return_value = (
            False, 'Неверный формат ссылки'
        )
        
        # Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            redirector.extract_short_code('invalid_url')
        
        assert exc_info.value.code == 'INVALID_SHORT_URL_FORMAT'
        assert 'Неверный формат ссылки' in str(exc_info.value.message)
    
    def test_extract_short_code_extraction_failed(self, redirector, mock_short_code_extractor):
        """Тест неудачного извлечения кода"""
        # Arrange
        mock_short_code_extractor.extract_code_from_url.return_value = None
        
        # Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            redirector.extract_short_code('https://short.ly/')
        
        assert exc_info.value.code == "SHORT_CODE_EXTRACTION_FAILED"
    
    def test_get_original_url_from_cache(self, sample_redirect_link, redirector, mock_cache_manager, mock_repository):
        """Тест получения URL из кэша"""
        # Arrange
        link_code = sample_redirect_link.short_code
        original_url = sample_redirect_link.original_url
        
        mock_cache_manager.get_original_url.return_value = original_url
        mock_repository.get_by_short_code.return_value = sample_redirect_link
        mock_repository.increment_clicks.return_value = True

        # Act
        result = redirector.get_original_url(original_url)
        
        # Assert
        assert isinstance(result, RedirectResult)
        assert result.original_url == original_url
        assert result.from_cache is True
        # не известно сколько кликов ,когда берем из кэша
        assert result.clicks is None
        mock_cache_manager.get_original_url.assert_called_once()
        # Проверяем, что обновили данные в БД и кэше
        mock_repository.increment_clicks.assert_called_once_with(link_code)
    
    def test_get_original_url_from_database(self, sample_redirect_link, redirector, mock_cache_manager, mock_repository):
        """Тест получения URL из базы данных"""
        # значение = 5 
        link_clicks = sample_redirect_link.clicks
        link_code= sample_redirect_link.short_code

        mock_cache_manager.get_original_url.return_value = None
        mock_repository.get_by_short_code.return_value = sample_redirect_link
        mock_repository.increment_clicks.return_value = True

        # Act
        result = redirector.get_original_url(f'https:/short.com/{link_code}')

        # Assert
        assert isinstance(result, RedirectResult)
        assert result.from_cache is False
        assert result.clicks == link_clicks + 1 # должно сработать инкрементирование

        # Проверка цепочки вызовов
        mock_repository.get_by_short_code.assert_called_once_with(link_code)
        mock_repository.increment_clicks.assert_called_once_with(link_code)
        mock_cache_manager.cache_link.assert_called_once()
    
    def test_get_original_url_not_found(self, redirector, mock_cache_manager, mock_repository):
        """Тест случая, когда ссылка не найдена (не существует в системе сервиса)"""
        mock_cache_manager.get_original_url.return_value = None
        mock_repository.get_by_short_code.return_value = None

        # Act & Assert
        with pytest.raises(LinkNotFoundError) as exc_info:
            redirector.get_original_url('https://short.com/notfound')

        assert 'не найдена' in str(exc_info.value)
        assert 'Короткий код' in str(exc_info.value)
    
    def test_get_original_url_without_cache(self, redirector_without_cache, mock_repository, sample_redirect_link):
        """Тест работы с отключенным кэшем"""
        code = sample_redirect_link.short_code
        mock_repository.get_by_short_code.return_value = sample_redirect_link
        mock_repository.increment_clicks.return_value = True

        # Act
        result = redirector_without_cache.get_original_url(f'https:/short.com/{code}')

        # Assert
        assert isinstance(result, RedirectResult)
        assert result.original_url == sample_redirect_link.original_url
        assert result.from_cache is False
        mock_repository.get_by_short_code.assert_called_once()
    
    def test_update_link_data_success(self, redirector, mock_repository, mock_cache_manager, sample_redirect_link):
        """Тест обновления данных ссылки после кэш-попадания"""
        code = sample_redirect_link.short_code
        mock_repository.get_by_short_code.return_value = sample_redirect_link
        mock_repository.increment_clicks.return_value = True

        # Act
        redirector._update_link_data(code)

        # Assert
        mock_repository.get_by_short_code.assert_called_once_with(code)
        mock_repository.increment_clicks.assert_called_once_with(code)
        mock_cache_manager.cache_link.assert_called_once()

    def test_update_link_data_with_exception(self, redirector, mock_repository, mock_logger):
        """Тест обработки исключения при обновлении данных"""
        # Arrange
        mock_repository.get_by_short_code.side_effect = Exception("DB error")
        
        # Act
        redirector._update_link_data("abc123")
        
        # Assert
        mock_logger.error.assert_called_once()
        assert "Ошибка при обновлении кэша" in mock_logger.error.call_args[0][0]
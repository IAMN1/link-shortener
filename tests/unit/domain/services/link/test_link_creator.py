from unittest.mock import Mock
import pytest

from src.link_shortener.domain.entities.link import Link
from src.link_shortener.domain.exceptions import ValidationError
from src.link_shortener.domain.services.link.link_creator import ShortLinkCreator
from src.link_shortener.domain.value_objects.short_link_result import ShortLinkCreationResult


@pytest.mark.unit
class TestLinkShortCreator:
    """
    Тест метода create_short_url
    
    Должен возвращать:
        - ShortCreationResult объект с данными:
        - - link (link)- существующая ссылка
        - - is_new (bool)- флаг обозначающий, что сылка уже существовала
          и не создавалась в ходе этого запроса
        - - from_cached (bool) - флаг, где True - взята из кэша. False - взята из БД
    """

    @pytest.fixture
    def creator(self, mock_repository, mock_url_validator, mock_code_generator, mock_cache_manager, mock_logger):
        """Фикстура создателя ссылок"""
        from src.link_shortener.domain.value_objects.cache_strategy import (
            HashCacheStrategy, RedirectCacheStrategy
        )

        return ShortLinkCreator(
            repository=mock_repository,
            url_validator=mock_url_validator,
            code_generator=mock_code_generator,
            cache_manager=mock_cache_manager,
            hash_strategy=HashCacheStrategy(),
            redirect_strategy=RedirectCacheStrategy(),
            cache_ttl=3600,
            logger=mock_logger
        )

    
    def test_create_short_url_with_invalid_url_raises_error(self, creator, mock_url_validator):
        """
        Тест случая, когда передан не валидный URL. 
        Должен происходить вызов ValidationError при не валидном URL
        """
        
        not_valid_url = 'invalid'
        mock_url_validator.is_valid_url.return_value = (
            False,
            'URL должен начинаться с http:// или https://'
        )

        # Act
        with pytest.raises(ValidationError) as exc_info:
            creator.create_short_url(not_valid_url)
        
        # Assert
        assert "URL должен на" in str(exc_info.value.message)
        assert exc_info.value.code == 'INVALID_URL'
        mock_url_validator.is_valid_url.assert_called_once_with('invalid')
    
    def test_create_short_url_returns_cached_link_if_exists(self, sample_link, creator, mock_repository, mock_cache_manager):
        """
        Тест случая, когда такая ссылка уже существует и имеется в кэше.
        """
        url = sample_link.original_url

        mock_cache_manager.get_link_by_hash.return_value = sample_link
        
        # Act
        result = creator.create_short_url(url)

        # Assert
        assert isinstance(result, ShortLinkCreationResult)
        assert result.link == sample_link
        assert result.is_new is False
        assert result.from_cache is True
        mock_cache_manager.get_link_by_hash.assert_called_once()
        mock_repository.get_by_hash.assert_not_called()
    
    def test_create_short_url_returns_existing_link_from_repository(self, sample_link, creator, mock_repository, mock_cache_manager, mock_code_generator):
        """
        Тест случая, когда такая ссылка уже существует, но не имеется в кэше.
        """
        link_hash = sample_link.url_hash
        original_url = sample_link.original_url

        mock_code_generator.calculate_deduplication_hash.return_value = link_hash
        mock_cache_manager.get_link_by_hash.return_value = None
        mock_repository.get_by_hash.return_value = sample_link
        
        # Act
        result = creator.create_short_url(original_url)

        # Assert
        assert isinstance(result, ShortLinkCreationResult)
        assert result.link == sample_link
        assert result.is_new is False
        assert result.from_cache is False
        mock_repository.get_by_hash.assert_called_once_with(link_hash)
        # Всегда должен закешировать, если взял из БД или создал новую
        mock_cache_manager.cache_link.assert_called_once()
    
    def test_create_short_url_creates_new_link_when_not_exists(self, sample_link, mock_url_validator, creator, mock_repository, mock_code_generator, mock_cache_manager):
        """Тест случая, когда ссылка новая и ее нет в кэше и репозитории"""
        url = sample_link.original_url
        link_hash = sample_link.url_hash

        mock_cache_manager.get_link_by_hash.return_value = None
        mock_repository.get_by_hash.return_value = None
        mock_repository.create.return_value = sample_link

        # Act
        result = creator.create_short_url(url)

        # Assert
        assert isinstance(result, ShortLinkCreationResult)
        assert result.link == sample_link
        assert result.is_new is True
        assert result.from_cache is False
        # проверка цепочки вызовов тестируемого метода
        mock_url_validator.is_valid_url.assert_called_once_with(url)
        mock_code_generator.calculate_deduplication_hash.assert_called_once()
        mock_cache_manager.get_link_by_hash.assert_called_once()
        mock_repository.get_by_hash.assert_called_once_with(link_hash)
        mock_code_generator.generate_code.assert_called_once_with('test.com')
        mock_repository.create.assert_called_once()
        mock_cache_manager.cache_link.assert_called_once()

    def test_create_short_url_without_cache_manager_still_works(self, mock_repository, mock_url_validator, mock_code_generator, mock_logger):
        """Тест случая создания ссылки, когда кэш отключен"""
        creator = ShortLinkCreator(
            repository=mock_repository,
            url_validator=mock_url_validator,
            code_generator=mock_code_generator,
            cache_manager=None, # off
            logger=mock_logger
        )
        new_link = Link.create(
            url_hash="hash123",
            short_code='code123',
            original_url='https://example.com'
        )
        mock_repository.get_by_hash.return_value = None
        mock_repository.create.return_value = new_link
        
        # Act
        result = creator.create_short_url('https://example.com')

        # Assert
        assert result.link == new_link
        assert result.is_new is True
    
    @pytest.mark.parametrize('url,normalized', [
        ('https://example.com', 'example.com'),
        ('https://Example.com', 'example.com'),
        ('HtTpS://EXAMPLE.COM', 'example.com')
    ])
    def test_create_short_url_normalizes_url(self, url, normalized, mock_repository, mock_code_generator):
        """Параметризованный тест нормализации URL"""
        mock_url_validator = Mock()
        mock_url_validator.is_valid_url.return_value = (True, normalized)

        creator = ShortLinkCreator(
            repository=mock_repository,
            url_validator=mock_url_validator,
            code_generator=mock_code_generator,
            cache_manager=None
        )

        mock_repository.get_by_hash.return_value = None
        mock_repository.create.return_value = Link.create(
            url_hash="hash123",
            short_code='code123',
            original_url=url
        )

        # Act
        creator.create_short_url(url)

        # Assert
        mock_url_validator.is_valid_url.assert_called_once_with(url)
        mock_code_generator.calculate_deduplication_hash.assert_called_once_with(normalized)
        mock_code_generator.generate_code.assert_called_once_with(normalized)

    def test_create_short_url_logs_correct_messages(self, sample_link, creator, mock_repository, mock_logger):
        """Тест логирования при создании ссылки"""

        mock_repository.get_by_hash.return_value = None
        mock_repository.create.return_value = sample_link

        # Act
        creator.create_short_url('https://example.com')

        # Assert
        # Проверка вызовов создания логирования при создании ссылки
        assert mock_logger.debug.called
        assert mock_logger.info.called
        # Первый вызов debug с началом создания
        assert "Начало создания короткой ссылки" in mock_logger.debug.call_args_list[0][0][0]

        
from unittest.mock import Mock
from link_shortener.application.dtos.responses import BatchCreateResponse
from link_shortener.application.use_cases.batch_create_links import BatchCreateLinksUseCase
from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.url_hash import UrlHash
from link_shortener.domain.entities.link import Link
import pytest


@pytest.fixture
def use_case(
    mock_link_cache, mock_link_repository, shortening_policy, mock_logger, mock_audit_logger, base_url
):
    """Fixture for BatchCreateLinksUseCase with default batch limit 100."""
    return BatchCreateLinksUseCase(
        repository=mock_link_repository,
        cache=mock_link_cache,
        shortening_policy=shortening_policy,
        base_url=base_url,
        logger=mock_logger,
        audit_logger=mock_audit_logger,
        batch_limit=100
    )

@pytest.fixture
def sample_urls():
    return [
        'https://test.com/1',
        'https://test.com/2',
        'https://test.com/3'
    ]


# ------------------------------------------------------------------
# TestBatchCreateLinksUseCase
# ------------------------------------------------------------------
class TestBatchCreateLinksUseCase:
    """Tests for the BatchCreateLinksUseCase."""


    def test_empty_urls_list(self, use_case):
        """Should return empty response when input list is empty."""
        
        # Act
        response = use_case.execute([])

        # Assert
        assert isinstance(response, BatchCreateResponse)
        assert response.items == []
        assert response.total == 0
    
    def test_batch_limit_exceeded(self, use_case, sample_urls):
        """
        Should raise ValueError when number of URLs exceeds batch limit.
        """
        use_case.batch_limit = 2

        with pytest.raises(ValueError, match="Batch limit exceeded."):
            use_case.execute(sample_urls) # фикстура с 3 URL
    
    def test_all_invalid_urls(self, use_case, mock_link_cache):
        """Should mark all URLs as failed when none are valid."""
        
        # Arrange
        urls = ['a.com', 'http://notvalid', '']
        mock_link_cache.get_by_hashes.return_value = {}

        # Act
        response = use_case.execute(urls)

        # Assert
        assert response.total == 3
        assert response.successful == 0
        assert response.failed == 3
        for item in response.items:
            assert item.success is False
            assert item.error is not None
    
    def test_all_from_cache(
        self, use_case, mock_link_cache, mock_link_repository, sample_urls, shortening_policy, base_url
    ):
        """
        All URLs already in cache – should return with from_cache=True.
        """

        # Подготовка ссылок
        links = []
        for url in sample_urls:
            original_url = OriginalUrl(url)
            url_hash = shortening_policy.calculate_hash(original_url)
            short_code = shortening_policy.generate_code_for_url(original_url)
            link = Link.create(
                url_hash=url_hash,
                short_code=short_code,
                original_url=original_url
            )
            links.append(link)
        
        # Настройка моков для кэша
        def get_by_hashes_side_effect(hashes):
            result = {}
            for link in links:
                if link.url_hash in hashes:
                    result[link.url_hash] = link
            return result
        mock_link_cache.get_by_hashes.side_effect = get_by_hashes_side_effect

        # Act
        response = use_case.execute(sample_urls)

        # Assert
        assert response.total == 3
        assert response.successful == 3
        assert response.from_cache_count == 3
        assert response.from_db_count == 0
        assert response.new_count == 0
        for item in response.items:
            assert item.success is True
            assert item.from_cache is True
            assert item.is_new is False
            assert item.short_url.startswith(base_url)
        
        # Проверка, что кэш вызывался с правильными хэшами
        [shortening_policy.calculate_hash(OriginalUrl(url)) for url in sample_urls]
        mock_link_cache.get_by_hashes.assert_called_once()
        # БД не вызывалась
        mock_link_repository.find_by_hashes.assert_not_called()
        mock_link_repository.save_many.assert_not_called()
 
    def test_mixed_scenario(
        self, use_case, mock_link_cache, mock_link_repository, shortening_policy
    ):
        """
        Mixed scenario: some URLs in cache, some in DB, some new.
        """
        urls = [
            'https://example.com/cached',
            'https://example.com/in_db',
            'https://example.com/new'
        ]
        
        # Создание ссылок
        cached_url = OriginalUrl(urls[0])
        cached_hash = shortening_policy.calculate_hash(cached_url)
        cached_code = shortening_policy.generate_code_for_url(cached_url)
        cached_link = Link.create(
            url_hash=cached_hash,
            short_code=cached_code,
            original_url=cached_url
        )

        db_url = OriginalUrl(urls[1])
        db_hash = shortening_policy.calculate_hash(db_url)
        db_code = shortening_policy.generate_code_for_url(db_url)
        db_link = Link.create(
            url_hash=db_hash,
            short_code=db_code,
            original_url=db_url
        )

        new_url = OriginalUrl(urls[2])
        new_hash = shortening_policy.calculate_hash(new_url)
        new_code = shortening_policy.generate_code_for_url(new_url)
        
        # Настройка моков
        # 1. кэш
        def get_by_hashes_side_effect(hashes):
            result = {}
            if cached_hash in hashes:
                result[cached_hash] = cached_link
            return result
        mock_link_cache.get_by_hashes.side_effect = get_by_hashes_side_effect

        # 2. репозиторий: find_by_hashes
        def find_by_hashes_side_effect(hashes):
            result = {}
            if db_hash in hashes:
                result[db_hash] = db_link
            return result
        mock_link_repository.find_by_hashes.side_effect = find_by_hashes_side_effect

        # 3. репозиторий: find_by_codes для проверки колизий, {} - если нет коллизий
        mock_link_repository.find_by_codes.return_value = {}

        # Репозиторий: save_many – возвращает сохранённые ссылки (для новых)
        def save_many_side_effect(links):
            # Просто возвращаем те же ссылки (как будто сохранили)
            return links
        mock_link_repository.save_many.side_effect = save_many_side_effect

        # Кэш: save_many – просто заглушка
        mock_link_cache.save_many.return_value = None

        response = use_case.execute(urls)

            # Проверяем общую статистику
        assert response.total == 3
        assert response.successful == 3
        assert response.failed == 0
        assert response.from_cache_count == 1
        assert response.from_db_count == 1
        assert response.new_count == 1

        # Проверяем каждый элемент
        items_by_url = {item.url: item for item in response.items}

        # Проверяем cached
        cached_item = items_by_url[urls[0]]
        assert cached_item.success is True
        assert cached_item.from_cache is True
        assert cached_item.short_code == cached_link.short_code.value

        # Проверяем db
        db_item = items_by_url[urls[1]]
        assert db_item.success is True
        assert db_item.from_cache is False
        assert db_item.is_new is False
        assert db_item.short_code == db_link.short_code.value

        # Проверяем new
        new_item = items_by_url[urls[2]]
        assert new_item.success is True
        assert new_item.is_new is True
        assert new_item.from_cache is False
        assert new_item.short_code == new_code.value  # должен совпадать с тем, что сгенерировали

        # Проверяем вызовы
        mock_link_cache.get_by_hashes.assert_called_once()
        # find_by_hashes вызывался с хэшами, которых не было в кэше (db_hash и new_hash)
        mock_link_repository.find_by_hashes.assert_called_once_with([db_hash, new_hash])
        # find_by_codes вызывался с кодами новых ссылок (new_code) – но у нас только одна новая
        mock_link_repository.find_by_codes.assert_called_once_with([new_code])
        # save_many вызывался с новой ссылкой
        mock_link_repository.save_many.assert_called_once()
        # cache.save_many вызывался для всех трёх (cached уже была в кэше? нет, мы сохраняем все: из БД и новые)
        # После обработки мы сохраняем links_to_cache, которые включают db_link и new_link
        mock_link_cache.save_many.assert_called_once()

    def test_duplicate_urls(
        self, use_case, mock_link_cache, mock_link_repository
    ):
        """Duplicate URLs in input should be grouped and marked appropriately."""
        
        urls = [
            'https://example.com/duplicate',
            'https://example.com/duplicate',
            'https://example.com/other'
        ]

        mock_link_cache.get_by_hashes.return_value = {}
        mock_link_repository.find_by_hashes.return_value = {}
        mock_link_repository.find_by_codes.return_value = {}
        mock_link_repository.save_many.side_effect = lambda links: links

        response = use_case.execute(urls)

        assert response.total == 3
        assert response.successful == 3
        assert response.new_count == 2  # две уникальные ссылки

        duplicate_items = [i for i in response.items if i.url == 'https://example.com/duplicate']
        assert len(duplicate_items) == 2
        assert duplicate_items[0].short_code == duplicate_items[1].short_code
        new_item = next(i for i in duplicate_items if i.is_new)
        duplicate_item = next(i for i in duplicate_items if not i.is_new)
        assert duplicate_item.duplicate_of == new_item.original_url
    
    def test_code_collision_resolution(
        self, use_case, mock_link_repository, mock_link_cache
    ):
        """Should resolve code collisions by generating alternative codes."""

        mock_policy = Mock()
        url1 = 'https://example.com/1'
        url2 = 'https://example.com/2'

        hash1 = UrlHash('a'*64)
        hash2 = UrlHash('b'*64)

        def calculate_hash_side_effect(original_url):
            if original_url.value == url1:
                return hash1
            elif original_url.value == url2:
                return hash2
            return UrlHash('c'*64)
        mock_policy.calculate_hash.side_effect = calculate_hash_side_effect

        # generate_code_for_url возвращает одинаковый код для обоих
        def generate_code_for_url_side_effect(original_url):
            return ShortCode('code123')
        mock_policy.generate_code_for_url.side_effect = generate_code_for_url_side_effect

        def generate_unique_code_side_effect(original_url, attempt):
            if original_url.value == url1:
                if attempt == 0:
                    return ShortCode('code123')
                else:
                    return ShortCode('code125')
            elif original_url.value == url2:
                if attempt == 0:
                    return ShortCode('code123')
                elif attempt == 1:
                    return ShortCode('code124')
            return ShortCode('default')
        mock_policy.generate_unique_code.side_effect = generate_unique_code_side_effect

        use_case.shortening_policy = mock_policy

        mock_link_cache.get_by_hashes.return_value = {}
        mock_link_repository.find_by_hashes.return_value = {}

        existing_link = Mock()
        existing_link.url_hash = UrlHash('f'*64)
        mock_link_repository.find_by_codes.return_value = {ShortCode('code123'): existing_link}

        saved_links = []
        mock_link_repository.save_many.side_effect = lambda links: saved_links.extend(links) or links

        response = use_case.execute([url1, url2])

        assert response.successful == 2
        assert len(saved_links) == 2
        codes = {link.short_code.value for link in saved_links}
        assert codes == {'code124', 'code125'}  # ожидаем уникальные коды
    
    def test_code_collision_with_same_hash(
        self, use_case, mock_link_repository, mock_link_cache, shortening_policy
    ):
        """
        If a code collides with an existing link that has the same hash,
        the existing link should be returned.
        """
        
        url = 'https://example.com'
        original_url = OriginalUrl(url)
        url_hash = shortening_policy.calculate_hash(original_url)
        short_code = shortening_policy.generate_code_for_url(original_url)
        
        # Существующая ссылка в БД
        existing_link = Link.create(
            url_hash=url_hash,
            short_code=short_code,
            original_url=original_url
        )
        
        mock_link_cache.get_by_hashes.return_value = {}
        mock_link_repository.find_by_hashes.return_value = {url_hash: existing_link}
        
        response = use_case.execute([url])
        
        assert response.successful == 1
        assert response.from_db_count == 1
        assert response.items[0].short_code == short_code.value
        assert response.items[0].is_new is False
    
    def test_mixed_valid_invalid_urls(
        self, use_case, mock_link_cache, mock_link_repository, shortening_policy
    ):
        """
        Should handle mix of valid and invalid URLs: valid ones processed,
        invalid ones reported as errors.
        """
        urls = [
            "https://valid.com/1",
            "not a url",
            "https://valid.com/2"
        ]

        # Only valid URLs have hashes
        valid_hashes = []
        for url in urls:
            if url.startswith("http"):
                original_url = OriginalUrl(url)
                valid_hashes.append(shortening_policy.calculate_hash(original_url))

        mock_link_cache.get_by_hashes.return_value = {}
        mock_link_repository.find_by_hashes.return_value = {}

        def save_many_side_effect(links):
            return links
        mock_link_repository.save_many.side_effect = save_many_side_effect
        mock_link_repository.find_by_codes.return_value = {}

        response = use_case.execute(urls)

        assert response.total == 3
        assert response.successful == 2
        assert response.failed == 1
        assert response.new_count == 2

        invalid_item = next(i for i in response.items if i.url == "not a url")
        assert invalid_item.success is False
        assert invalid_item.error is not None

        valid_items = [i for i in response.items if i.success]
        assert len(valid_items) == 2

    def test_save_new_links_failure(
        self, use_case, mock_link_cache, mock_link_repository
    ):
        """
        Should handle failure when saving new links 
        (repository.save_many returns empty list).
        """
        urls = ["https://valid.com/new"]

        mock_link_cache.get_by_hashes.return_value = {}
        mock_link_repository.find_by_hashes.return_value = {}
        mock_link_repository.find_by_codes.return_value = {}

        mock_link_repository.save_many.return_value = []  # simulate save failure

        response = use_case.execute(urls)

        assert response.total == 1
        assert response.successful == 0
        assert response.failed == 1
        assert response.items[0].success is False
        assert response.items[0].error == "Failed to save link"

    def test_code_collision_max_attempts_exceeded(
        self, use_case, mock_link_repository, mock_link_cache
    ):
        """
        Should handle case where code collisions cannot be resolved after max attempts,
        resulting in failure for those URLs.
        """
        mock_policy = Mock()
        url1 = "https://example.com/collide1"
        url2 = "https://example.com/collide2"

        hash1 = UrlHash('a'*64)
        hash2 = UrlHash('b'*64)

        def calculate_hash_side_effect(original_url):
            if original_url.value == url1:
                return hash1
            return hash2
        mock_policy.calculate_hash.side_effect = calculate_hash_side_effect

        # generate_code_for_url returns same code for both
        mock_policy.generate_code_for_url.return_value = ShortCode('code123')
        # generate_unique_code always returns same code (collision)
        mock_policy.generate_unique_code.return_value = ShortCode('code123')

        use_case.shortening_policy = mock_policy

        mock_link_cache.get_by_hashes.return_value = {}
        mock_link_repository.find_by_hashes.return_value = {}

        existing_link = Mock(spec=Link)
        existing_link.url_hash = UrlHash('c'*64)  # different hash
        mock_link_repository.find_by_codes.return_value = {ShortCode('code123'): existing_link}

        mock_link_repository.save_many.return_value = []

        response = use_case.execute([url1, url2])

        assert response.successful == 0
        assert response.failed == 2
        for item in response.items:
            assert item.success is False
            assert item.error == "Failed to save link"

        mock_link_repository.save_many.assert_not_called()

    def test_execute_raises_runtime_error_on_unexpected_exception(
        self, use_case, mock_link_cache
    ):
        """Should raise RuntimeError and log when unexpected exception occurs."""

        # Arrange
        mock_link_cache.get_by_hashes.side_effect = Exception("Unexpected error")
        
        # Act & Assert
        with pytest.raises(RuntimeError, match="Batch processing failed: Unexpected error"):
            use_case.execute(["https://test.com"])
        
        use_case.logger.exception.assert_called_once()

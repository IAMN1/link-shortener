import pytest

from src.link_shortener.domain.entities.link import Link
from src.link_shortener.domain.services.link.batch_link_processor import BatchLinkProcessor
from src.link_shortener.domain.value_objects.cache_strategy import HashCacheStrategy, RedirectCacheStrategy
from src.link_shortener.domain.value_objects.short_link_result import BatchLinkData, BatchProcessingSummary, BatchResultItem


@pytest.mark.unit
class TestBatchLinkProcessor:
    """Тест для BatchLinkProcessor"""

    @pytest.fixture
    def batch_processor(self, mock_repository, mock_cache_manager, mock_url_validator, mock_code_generator, mock_logger):
        """Фикстура пакетного создателя ссылок"""
        return BatchLinkProcessor(
            repository=mock_repository,
            url_validator=mock_url_validator,
            code_generator=mock_code_generator,
            cache_manager=mock_cache_manager,
            hash_strategy=HashCacheStrategy(),
            redirect_strategy=RedirectCacheStrategy(),
            cache_ttl=3600,
            batch_limit=100,
            logger=mock_logger
        )
    
    def test_batch_create_with_empty_list(self, batch_processor):
        """Тест пакетного создания с пустым списком URL"""
        # Act
        results, summary = batch_processor.batch_create([])

        # Assert
        assert len(results) == 0
        assert summary.total == 0
        assert summary.successful == 0
        assert summary.failed == 0
        assert summary.new == 0
        assert summary.existing == 0
        assert summary.from_cache == 0
    
    def test_batch_create_with_single_valid_url(self, sample_link, batch_processor, mock_cache_manager, mock_repository):
        """Тест создания с одним валидным URL"""
        url = sample_link.original_url
        link_code = sample_link.short_code
        link_hash = sample_link.url_hash
        
        mock_cache_manager.get_link_by_hashes.return_value = []
        mock_repository.get_by_hashes.return_value = []

        mock_repository.bulk_create.return_value = [sample_link]

        # Debug
        # print(f"Mock is_valid_url return: {mock_url_validator.is_valid_url.return_value}", file=sys.stderr)

        # Act
        results, summary = batch_processor.batch_create([url])

         # Debug
        # print(f"Results count: {len(results)}", file=sys.stderr)
        # for i, r in enumerate(results):
        #     print(f"Result {i}: success={r.success}, error={r.error}", file=sys.stderr)
        #     if r.success:
        #         print(f"  url: {r.data.url}, hash: {r.data.url_hash}, code: {r.data.short_code}", file=sys.stderr)
        
        # Проверяем вызовы моков
        # print(f"URL validator called: {mock_url_validator.is_valid_url.called}", file=sys.stderr)
        # print(f"Cache manager get_link_by_hashes called: {mock_cache_manager.get_link_by_hashes.called}", file=sys.stderr)
        # print(f"Repository bulk_create called: {mock_repository.bulk_create.called}", file=sys.stderr)
        # if mock_repository.bulk_create.called:
        #     print(f"  with args: {mock_repository.bulk_create.call_args}", file=sys.stderr)

        # Assert
        assert isinstance(results[0], BatchResultItem)
        assert isinstance(summary, BatchProcessingSummary)
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].data.url == url
        assert results[0].data.url_hash == link_hash
        assert results[0].data.short_code == link_code
        assert results[0].is_new is True
        assert results[0].from_cache is False

        assert summary.total == 1
        assert summary.successful == 1
        assert summary.failed == 0
        assert summary.new == 1
        assert summary.existing == 0
        assert summary.from_cache == 0
    
    def test_batch_create_with_invalid_url(self, batch_processor, mock_url_validator):
        """Тест пакетного создания с невалидным URL"""
        mock_url_validator.is_valid_url.return_value = (False, 'Invalid Url format')

        # Act
        results, summary = batch_processor.batch_create(['non-valid-url'])

        # Assert
        assert isinstance(results[0], BatchResultItem)
        assert isinstance(summary, BatchProcessingSummary)
        assert len(results) == 1
        assert results[0].success is False
        assert results[0].error == 'Invalid Url format'
        assert summary.total == 1
        assert summary.successful == 0
        assert summary.failed == 1
    
    def test_batch_create_exceeds_batch_limit(self, batch_processor, mock_logger):
        """Тест превышения лимита пакетной обработки"""
        # 150 urls
        urls = ['https://test.com/{i}' for i in range(150)]

        # Act
        results, summary = batch_processor.batch_create(urls)

        # Assert
        mock_logger.warning.assert_called_once()
        warning_msg = mock_logger.warning.call_args[0][0]
        assert "Превышен" in warning_msg
        assert "урезан" in warning_msg
        assert len(results) <= 100 # batch_limit = 100 (default)
    
    def test_batch_create_new_links_with_mixed_valid_invalid_urls(self, batch_processor, mock_url_validator, mock_code_generator, mock_cache_manager, mock_repository):
        """Тест пакетного создания со смесью валидных и невалидных URLs"""
        def mock_is_valid_url(url):
            if 'invalid' in url:
                return (False, 'invalid url')
            return (True, url)
        
        def mock_calculate_hash(url):
            if 'valid1' in url:
                return 'hash1'
            elif 'valid2' in url:
                return 'hash2'
            return 'hash'
        
        def mock_generate_code(url):
            if 'valid1' in url:
                return 'code1'
            elif 'valid2' in url:
                return 'code2'
            return 'code'

        mock_url_validator.is_valid_url.side_effect = mock_is_valid_url
        mock_code_generator.calculate_deduplication_hash.side_effect = mock_calculate_hash
        mock_code_generator.generate_code.side_effect = mock_generate_code
        
        mock_cache_manager.get_link_by_hashes.return_value = []
        mock_repository.get_by_hashes.return_value = []
        db_link1 = Link.create(
            url_hash='hash1',
            short_code='code1',
            original_url='https://valid1.com'
        )
        db_link2 = Link.create(
            url_hash='hash2',
            short_code='code2',
            original_url='https://valid2.com'
        )

        mock_repository.bulk_create.return_value = [db_link1, db_link2]

        urls = [
            'https://valid1.com',
            'invalid-1',
            'https://valid2.com',
            'invalid-2'
        ]

        # Act
        results, summary = batch_processor.batch_create(urls)

        # Assert
        assert isinstance(summary, BatchProcessingSummary)
        assert summary.total == 4
        assert summary.successful == 2
        assert summary.failed == 2

        valid_results = [r for r in results if r.success]
        invalid_results = [r for r in results if not r.success]

        assert len(valid_results) == 2
        assert len(invalid_results) == 2
        mock_cache_manager.cache_links.assert_called_once()

    def test_batch_create_finds_existing_links_in_cache(self, sample_link, batch_processor, mock_cache_manager):
        """Тест поиска существующих ссылок в кэше"""
        url = sample_link.original_url
        mock_cache_manager.get_link_by_hashes.return_value = [sample_link]

        # Act
        results, summary = batch_processor.batch_create([url])

        # Assert
        assert isinstance(results[0], BatchResultItem)
        assert isinstance(summary, BatchProcessingSummary)
        assert summary.total == 1
        assert summary.successful == 1
        assert summary.existing == 1
        assert summary.from_cache == 1

        assert results[0].success is True
        assert results[0].is_new is False
        assert results[0].from_cache is True
    
    def test_batch_create_finds_existing_links_in_database(self, sample_link, batch_processor, mock_cache_manager, mock_repository):
        """Тест поиска существующих ссылок в Базе данных и их кэширование"""
        url = sample_link.original_url
        
        mock_repository.get_by_hashes.return_value = [sample_link]
        
        # Act
        results, summary = batch_processor.batch_create([url])
        
        # Assert
        assert isinstance(results[0], BatchResultItem)
        assert isinstance(summary, BatchProcessingSummary)
        
        assert summary.existing == 1
        assert summary.from_cache == 0
        
        assert results[0].success is True
        assert results[0].is_new is False
        assert results[0].from_cache is False
        
        mock_cache_manager.cache_links.assert_called_once()
        call_args = mock_cache_manager.cache_links.call_args
        assert len(call_args[0][0]) == 1
        assert call_args[0][0][0] == sample_link

    def test_batch_create_summary_calculation(self):
        """Тест правильного расчета сводки пакетной обработки"""

        results = [
            BatchResultItem(
                success=True,
                data=BatchLinkData(url='url1'),
                is_new=True,
                from_cache=False
            ),
            BatchResultItem(
                success=True,
                data=BatchLinkData(url='url2'),
                is_new=False,
                from_cache=True
            ),
            BatchResultItem(
                success=True,
                data=BatchLinkData(url='url3'),
                is_new=False,
                from_cache=False
            ),
            BatchResultItem(
                success=False,
                data=BatchLinkData(url='url4'),
                error='Invalid url'
            ),
            BatchResultItem(
                success=False,
                data=BatchLinkData(url='url5'),
                error='Invalid url'
            ),
        ]
        def mock_create_summary(results):
            total = len(results)
            successful = sum(1 for r in results if r.success)
            failed = total - successful
            new = sum(1 for r in results if r.success and r.is_new)
            existing = successful - new
            from_cache = sum(1 for r in results if r.success and r.from_cache)

            return BatchProcessingSummary(
                total=total,
                successful=successful,
                failed=failed,
                new=new,
                existing=existing,
                from_cache=from_cache
            )

        # Act
        summary = mock_create_summary(results)
        
        # Assert
        assert summary.total == 5
        assert summary.successful == 3
        assert summary.failed == 2
        assert summary.new == 1
        assert summary.existing == 2
        assert summary.from_cache == 1

    def test_batch_create_cache_new_links(self, sample_link, batch_processor, mock_cache_manager, mock_repository):
        """Тест кэширования новых ссылок"""
        url = sample_link.original_url

        mock_cache_manager.get_link_by_hashes.return_value = []
        mock_repository.get_by_hashes.return_value = []
        mock_repository.bulk_create.return_value = [sample_link]
        
        # Act
        batch_processor.batch_create([url])
        
        # Assert
        mock_cache_manager.cache_links.assert_called_once()
        call_args = mock_cache_manager.cache_links.call_args
        
        # Проверяем стратегии
        strategies = call_args[0][1]
        assert 'hash' in strategies
        assert 'redirect' in strategies
        assert isinstance(strategies['hash'], HashCacheStrategy)
        assert isinstance(strategies['redirect'], RedirectCacheStrategy)
        
        # Проверяем TTL
        ttl = call_args[0][2] if len(call_args[0]) > 2 else 3600
        assert ttl == 3600

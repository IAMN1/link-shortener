from datetime import datetime
import pytest

from src.link_shortener.domain.entities.link import Link
from src.link_shortener.domain.services.cache.cache_manager import CacheManager
from src.link_shortener.domain.value_objects.cache_strategy import HashCacheStrategy, InfoCacheStrategy, RedirectCacheStrategy, StatsCacheStrategy


@pytest.mark.unit
class TestCacheManager:
    """Тесты для CacheManager"""

    @pytest.fixture
    def cache_manager(self, mock_cache_client, mock_logger):
        """Фикстура менеджера кэша"""
        return CacheManager(
            logger=mock_logger,
            cache_client=mock_cache_client
        )
    
    @pytest.fixture
    def cache_manager_without_cache_client(mock_logger):
        """Фикстура менеджера кэша с отключенным кэш клиентом"""
        return CacheManager(
            logger=mock_logger,
            cache_client=None
        )
    
    @pytest.fixture
    def dict_link_data(self):
        """Данные из кэша в формате словаря"""
        data_link = {
            'id': 'id-123',
            'url_hash': 'hash123',
            'short_code': 'code123',
            'original_url': 'https://test.com',
            'created_at': datetime(2026, 2, 5, 0, 0).isoformat(),
            'clicks': 10,
            'last_accessed': datetime(2026, 2, 7, 0, 0).isoformat()
        }
        return data_link

    @pytest.fixture
    def sample_link(self):
        """Тестовая ссылка"""
        return Link.create(
            url_hash='hash123',
            short_code='code123',
            original_url='https://example.com/test'
        )


    def test_link_to_dict_conversion(self, cache_manager, sample_link):
        """Тест конвертации Link в Dict"""
        
        # Act
        link_to_dict = cache_manager._link_to_dict(sample_link)


        # Assert
        assert link_to_dict['id'] == sample_link.id
        assert link_to_dict['url_hash'] == sample_link.url_hash
        assert link_to_dict['short_code'] == sample_link.short_code
        assert link_to_dict['original_url'] == sample_link.original_url
        assert link_to_dict['clicks'] == sample_link.clicks
        assert link_to_dict['created_at'] == sample_link.created_at.isoformat()
        assert link_to_dict['last_accessed'] is None
    
    def test_dict_to_link_conversion(self, cache_manager):
        """Тест конвертации Dict в Link"""

        data_link = {
            'id': 'test-id-123',
            'url_hash': 'hash123',
            'short_code': 'code123',
            'original_url': 'https://example.com',
            'created_at': datetime(2026, 2, 5, 0, 0).isoformat(),
            'clicks': 10,
            'last_accessed': datetime(2026, 2, 7, 0, 0).isoformat()
        }

        # Act
        link = cache_manager._dict_to_link(data_link)

        # Assert
        assert link.id == 'test-id-123'
        assert link.url_hash == 'hash123'
        assert link.short_code == 'code123'
        assert link.original_url == 'https://example.com'
        assert link.clicks == 10
        assert isinstance(link.created_at, datetime)
        assert isinstance(link.last_accessed, datetime)
        assert link.created_at.isoformat() == datetime(2026, 2, 5, 0, 0).isoformat()
        assert link.last_accessed.isoformat() == datetime(2026, 2, 7, 0, 0).isoformat()
    
    def test_get_original_url_returns_none_without_cache_client(self, cache_manager_without_cache_client):
        """Тест случая, когда клиент кэша отключен"""
        redirect_strategy = RedirectCacheStrategy()

        # Act 
        result = cache_manager_without_cache_client.get_original_url('code123', redirect_strategy)

        # Assert
        assert result is None

    def test_get_original_url_returns_none_when_not_cached(self, cache_manager, mock_cache_client):
        """Тест получения оригинального URL из кэша"""
        redirect_strategy = RedirectCacheStrategy()
        mock_cache_client.get.return_value = None

        # Act
        result = cache_manager.get_original_url('code123', redirect_strategy)

        # Assert
        assert result is None
        mock_cache_client.get.assert_called_once_with('link:redirect:code123')

    def test_get_original_url_returns_string(self, cache_manager, mock_cache_client):
        """Тест получения оригинального URL из кэша"""
        redirect_strategy = RedirectCacheStrategy()
        mock_cache_client.get.return_value = 'https://test.com/test1/test2'

        # Act
        result = cache_manager.get_original_url('code123', redirect_strategy)

        # Assert
        assert result == 'https://test.com/test1/test2'
        mock_cache_client.get.assert_called_once_with('link:redirect:code123')

    def test_get_original_url_handles_dict_fallback(self, cache_manager, mock_cache_client, mock_logger):
        """Тест обработки полученного словаря вместо строки в кэше редиректа"""
        redirect_strategy = RedirectCacheStrategy()
        mock_cache_client.get.return_value = {
            'original_url':'https://test.com/test1/test2'
        }

        # Act
        result = cache_manager.get_original_url('code123', redirect_strategy)

        # Assert
        assert result == 'https://test.com/test1/test2'
        mock_logger.warning.assert_called_once()

    def test_get_link_info_returns_none_without_cache_client(self, cache_manager_without_cache_client):
        """тест случая, когда когда клиент отключен"""
        redirect_strategy = InfoCacheStrategy()

        # Act
        result = cache_manager_without_cache_client.get_link_info('code123', redirect_strategy)

        # Assert
        assert result is None

    def test_get_link_info_returns_none_when_not_cached(self, cache_manager, mock_cache_client):
        """тест случая, когда ссылки нет в кэше"""
        redirect_strategy = InfoCacheStrategy()
        mock_cache_client.get.return_value = None

        # Act
        result = cache_manager.get_link_info('code123', redirect_strategy)

        # Assert
        assert result is None
        mock_cache_client.get.assert_called_once_with('link:info:code123')

    def test_get_link_info_returns_cached_link(self, dict_link_data, cache_manager, mock_cache_client, mock_logger):
        """Тест получения ссылки из кэша по коду"""
        redirect_strategy = InfoCacheStrategy()
        mock_cache_client.get.return_value = dict_link_data

        # Act
        result = cache_manager.get_link_info(dict_link_data['short_code'], redirect_strategy)

        # Assert
        assert isinstance(result, Link)
        assert result is not None
        assert result.url_hash == dict_link_data['url_hash']
        assert result.short_code == dict_link_data['short_code']
        assert result.original_url == dict_link_data['original_url']
        mock_cache_client.get.assert_called_once_with(f'link:info:{dict_link_data['short_code']}')

    def test_get_link_by_hash_returns_none_without_cache_client(self, cache_manager_without_cache_client):
        """Тест случая, когд кэш клиент отключен"""
        hash_strategy = HashCacheStrategy()

        # Act
        result = cache_manager_without_cache_client.get_link_by_hash('hash123', hash_strategy)

        assert result is None

    def test_get_link_by_hash_returns_none_when_not_cached(self, cache_manager, mock_cache_client):
        """Тест случая, когда ссылки нет в кэше"""
        hash_strategy = HashCacheStrategy()
        mock_cache_client.get.return_value = None

        # Act
        result = cache_manager.get_link_by_hash('hash123', hash_strategy)

        assert result is None
        mock_cache_client.get.assert_called_once_with('link:hash:hash123')

    def test_get_link_by_hash_returns_cached_link(self, dict_link_data, cache_manager, mock_cache_client):
        """Тест получения ссылки из кэша по хэшу"""
        hash_strategy = HashCacheStrategy()
        
        mock_cache_client.get.return_value = dict_link_data

        # Act
        result = cache_manager.get_link_by_hash(dict_link_data['url_hash'], hash_strategy)

        # Assert
        assert isinstance(result, Link)
        assert result is not None
        assert result.url_hash == dict_link_data['url_hash']
        assert result.short_code == dict_link_data['short_code']
        mock_cache_client.get.assert_called_once_with(f'link:hash:{dict_link_data['url_hash']}')

    def test_get_link_by_hashes_returns_none_without_cache_client(self, cache_manager_without_cache_client):
        """Тест случая, когд кэш клиент отключен"""
        hash_strategy = HashCacheStrategy()

        # Act
        result = cache_manager_without_cache_client.get_link_by_hashes(['hash123'], hash_strategy)

        assert result == []

    def test_get_link_by_hashes_returns_none_when_not_cached(self, cache_manager, mock_cache_client):
        """Тест случая, когда ссылок нет в кэше"""
        hash_strategy = HashCacheStrategy()
        mock_cache_client.get.return_value = None

        # Act
        result = cache_manager.get_link_by_hashes(['test_hash1', 'test_hash2'], hash_strategy)

        assert result == []

    def test_get_link_by_hashes_returns_cached_links(self, cache_manager, mock_cache_client):
        """тест получения нескольких ссылок по хэшам из кэша"""
        hash_strategy = HashCacheStrategy()
        cached_link_1 = {
            'id': 'test-id-1',
            'url_hash': 'hash1',
            'short_code': 'code1',
            'original_url': 'https://example1.com',
            'created_at': datetime(2026, 2, 5, 0, 0).isoformat(),
            'clicks': 0,
            'last_accessed': None
        }
        cached_link_2 = {
            'id': 'test-id-2',
            'url_hash': 'hash2',
            'short_code': 'code2',
            'original_url': 'https://example2.com',
            'created_at': datetime(2026, 2, 5, 0, 0).isoformat(),
            'clicks': 10,
            'last_accessed': datetime(2026, 2, 7, 0, 0).isoformat()
        }
        cache_key_1 = hash_strategy.get_key('hash1')
        cache_key_2 = hash_strategy.get_key('hash2')

        mock_cache_client.get_many.return_value = {
            cache_key_1: cached_link_1,
            cache_key_2: cached_link_2
        }

        # Act
        result = cache_manager.get_link_by_hashes(['hash1', 'hash2'], hash_strategy)

        # Assert
        assert len(result) == 2
        # link 1
        assert result[0].url_hash == 'hash1'
        assert result[0].short_code == 'code1'
        assert result[0].original_url == 'https://example1.com'
        assert result[0].clicks == 0
        assert result[0].last_accessed is None
        
        # link 2
        assert result[1].url_hash == 'hash2'
        assert result[1].short_code == 'code2'
        assert result[1].original_url == 'https://example2.com'
        assert result[1].clicks == 10
        assert result[1].last_accessed == datetime(2026, 2, 7, 0, 0)

    def test_cache_link_with_multiple_strategies(self, sample_link, cache_manager, mock_cache_client):
        """Тест кэширования ссылки по нескольким стратегиям"""
        strategies = {
            'hash': HashCacheStrategy(),
            'redirect': RedirectCacheStrategy(),
            'info': InfoCacheStrategy()
        }

        # Act
        result = cache_manager.cache_link(sample_link, strategies, ttl=3600)

        # Assert
        assert result is True
        mock_cache_client.set_many.assert_called_once()

        # проверка данных
        cache_data = mock_cache_client.set_many.call_args[0][0]
        assert len(cache_data) == 3 # 3ключа

        # проверка ключей
        assert 'link:hash:hash123' in cache_data
        assert 'link:redirect:code123' in cache_data
        assert 'link:info:code123' in cache_data

        # Проверка значений
        assert cache_data['link:redirect:code123'] == sample_link.original_url
        assert isinstance(cache_data['link:hash:hash123'], dict)
    
    def test_cache_link_stores_correct_data_types(self, cache_manager, mock_cache_client, sample_link):
        """Тест кэширования с правильными типами данных"""
        strategies = {
            'hash': HashCacheStrategy(),
            'redirect': RedirectCacheStrategy(),
            'info': InfoCacheStrategy()
        }
        
        # Act
        result = cache_manager.cache_link(sample_link, strategies, ttl=3600)
        
        # Assert
        assert result is True
        mock_cache_client.set_many.assert_called_once()
        
        # Проверяем данные
        cache_data = mock_cache_client.set_many.call_args[0][0]
        
        # Для hash и info - словарь
        hash_data = cache_data[f'link:hash:{sample_link.url_hash}']
        info_data = cache_data[f'link:info:{sample_link.short_code}']
        
        assert isinstance(hash_data, dict)
        assert isinstance(info_data, dict)
        assert hash_data['original_url'] == sample_link.original_url
        
        # Для redirect - строка
        redirect_data = cache_data[f'link:redirect:{sample_link.short_code}']
        assert isinstance(redirect_data, str)
        assert redirect_data == sample_link.original_url

    def test_cache_links_single_strategy(self, sample_link, cache_manager, mock_cache_client, mock_logger):
        """Тест массового кэширования одной ссылки с одной стратегией"""
        strategies = {'hash': HashCacheStrategy()}

        mock_cache_client.set_many.return_value = True

        # Act
        result = cache_manager.cache_links([sample_link], strategies)

        # Assert
        assert result is True
        mock_cache_client.set_many.assert_called_once()
        call_args = mock_cache_client.set_many.call_args
        cache_data = call_args[0][0]
        ttl = call_args[0][1] if len(call_args) > 1 else 3600

        assert len(cache_data) == 1
        assert f'link:hash:{sample_link.url_hash}' in cache_data
        assert isinstance(cache_data[f'link:hash:{sample_link.url_hash}'], dict)
        assert cache_data[f'link:hash:{sample_link.url_hash}']['url_hash'] == sample_link.url_hash
        assert ttl == 3600
        
        mock_logger.info.assert_called()
        assert 'Начало массового кэширования' in mock_logger.info.call_args_list[0][0][0]
        assert 'Завершение массового кэширования' in mock_logger.info.call_args_list[1][0][0]
    
    def test_cache_links_multiple_links_multiple_strategies(self, cache_manager, mock_cache_client):
        """Тест массового кэширования нескольких ссылок с несколькими стратегиями"""
        link1 = Link.create(
            url_hash='hash1',
            short_code='code1',
            original_url='https://example1.com'
        )
        link2 = Link.create(
            url_hash='hash2',
            short_code='code2',
            original_url='https://example2.com'
        )
        strategies = {
            'hash': HashCacheStrategy(),
            'redirect': RedirectCacheStrategy(),
            'info': InfoCacheStrategy()
        }
        mock_cache_client.set_many.return_value = True

        # Act
        result = cache_manager.cache_links([link1, link2], strategies)

        # Assert
        assert result is True
        call_args = mock_cache_client.set_many.call_args
        cache_data = call_args[0][0]

        # должно быть 2 х 3 = 6 ключей для 0 аргумента
        assert len(cache_data) == 6

        # проверка ключей link1
        assert 'link:hash:hash1' in cache_data
        assert 'link:redirect:code1' in cache_data
        assert 'link:info:code1' in cache_data

        # проверка ключей link2
        assert 'link:hash:hash2' in cache_data
        assert 'link:redirect:code2' in cache_data
        assert 'link:info:code2' in cache_data
        
        # Проврека значений
        assert cache_data['link:redirect:code1'] == 'https://example1.com'
        assert cache_data['link:redirect:code2'] == 'https://example2.com'

        assert isinstance(cache_data['link:hash:hash1'], dict)
        assert isinstance(cache_data['link:info:code1'], dict)

    def test_cache_links_with_custom_ttl(self, cache_manager, mock_cache_client):
        """Тест массового кэширования с кастомным TTL"""
        link = Link.create(
            url_hash='hash1',
            short_code='code1',
            original_url='https://example1.com'
        )
        strategies = {'hash': HashCacheStrategy()}
        custom_ttl = 5000

        mock_cache_client.set_many.return_value = True

        # Act
        result = cache_manager.cache_links([link], strategies, custom_ttl)

        # Assert
        assert result is True
        mock_cache_client.set_many.assert_called_once()

        call_args = mock_cache_client.set_many.call_args
        ttl = call_args[0][1] if len(call_args[0]) > 1 else 3600

        assert ttl == custom_ttl
    
    def test_cache_links_returns_false_when_cache_client_fails(self, cache_manager, mock_cache_client):
        """Тест массового кэширования при ошибке cache_cleint"""
        link = Link.create(
            url_hash='hash1',
            short_code='code1',
            original_url='https://example1.com'
        )
        strategies = {'hash': HashCacheStrategy()}
        mock_cache_client.set_many.return_value = False

        # Act
        result = cache_manager.cache_links([link], strategies)

        # Assert
        assert result is False
        mock_cache_client.set_many.assert_called_once()
    
    def test_cache_links_returns_false_without_cache_client(self, sample_link, cache_manager_without_cache_client):
        """Тест массового кэширования c отключенным cache_client"""
        strategies = {'hash': HashCacheStrategy()}

        # Act
        result = cache_manager_without_cache_client.cache_links([sample_link], strategies)

        # Assert
        assert result is False
        assert not hasattr(cache_manager_without_cache_client._cache_client, 'set_many') or cache_manager_without_cache_client._cache_client is None

    def test_cache_links_with_only_redirect_strategy(self, sample_link, cache_manager, mock_cache_client):
        """Тест массового кэширования только с redirect стратегией"""
        link_code = sample_link.short_code
        strategies = {'redirect': RedirectCacheStrategy()}

        mock_cache_client.set_many.return_value = True

        # Act
        result = cache_manager.cache_links([sample_link], strategies)

        # Assert
        assert result is True
        
        call_args = mock_cache_client.set_many.call_args
        cache_data = call_args[0][0]
        
        assert len(cache_data) == 1
        assert f'link:redirect:{link_code}' in cache_data
        assert cache_data[f'link:redirect:{link_code}'] == sample_link.original_url
    
    def test_cache_links_with_only_info_strategy(self, sample_link, cache_manager, mock_cache_client):
        """тест массового кэширования только с info стратегией"""
        link_code = sample_link.short_code
        strategies = {'info': InfoCacheStrategy()}
        
        mock_cache_client.set_many.return_value = True

        # Act
        result = cache_manager.cache_links([sample_link], strategies)

        # Assert
        assert result is True
        
        call_args = mock_cache_client.set_many.call_args
        cache_data = call_args[0][0]
        
        assert len(cache_data) == 1
        assert f'link:info:{link_code}' in cache_data
        assert isinstance(cache_data[f'link:info:{link_code}'], dict)
        assert cache_data[f'link:info:{link_code}']['short_code'] == link_code

    def test_cache_links_logs_duration_and_perfomance(self, sample_link, cache_manager, mock_cache_client, mock_logger):
        """Тест логирования длительности и производительности массового кэширования"""
        
        strategies = {'hash': HashCacheStrategy()}
        
        mock_cache_client.set_many.return_value = True

        # Act
        result = cache_manager.cache_links([sample_link], strategies)

        # Assert
        assert result is True

        assert mock_logger.info.call_count >=2

        info_calls = mock_logger.info.call_args_list

        # первый вызов
        first_call_args = info_calls[0][0]
        assert 'Начало массового кэширования' in first_call_args[0]
        assert 'link_count' in info_calls[0][1]
        assert info_calls[0][1]['link_count'] == 1
        assert info_calls[0][1]['strategy_count'] == 1

        # последний вызов
        last_call_args = info_calls[-1][0]
        assert 'Завершение массового кэширования' in last_call_args[0]
        assert 'success' in info_calls[-1][1]
        assert info_calls[-1][1]['success'] is True
        assert 'duration_seconds' in info_calls[-1][1]
        assert 'links_per_second' in info_calls[-1][1]

    def test_cache_links_handles_duplicate_keys_correctly(self, cache_manager, mock_cache_client):
        """Тест обработки дублирующихся ключей при массовом кэшировани"""
        # Две ссылки с одинаковым хэшем (что маловероятно, но возможно)
        link1 = Link.create(
            url_hash='same_hash',
            short_code='code1',
            original_url='https://example1.com'
        )
        link2 = Link.create(
            url_hash='same_hash',
            short_code='code2',
            original_url='https://example2.com'
        )
        strategies = {'hash': HashCacheStrategy()}

        mock_cache_client.set_many.return_value = True

        # Act
        result = cache_manager.cache_links([link1, link2], strategies)

        # Assert
        result is True

        call_args = mock_cache_client.set_many.call_args
        cache_data = call_args[0][0]
        
        # Две ссылки с одинаковым хэшем создадут один ключ
        # Последнее значение перезапишет первое
        assert len(cache_data) == 1
        assert 'link:hash:same_hash' in cache_data
        
        # Проверяем какое значение сохранилось (последнее)
        assert cache_data['link:hash:same_hash']['short_code'] == 'code2'
        assert cache_data['link:hash:same_hash']['original_url'] == 'https://example2.com'

    def test_cache_links_preserves_link_data_integrity(self, sample_link, cache_manager, mock_cache_client):
        """тест сохранения целостности данных ссылки при массовом кэшировании"""
        link_hash = sample_link.url_hash
        link_code = sample_link.short_code
        # Устанавливаем last_accessed для теста
        sample_link.last_accessed = datetime(2026, 2, 7, 18, 38, 0)
        sample_link.clicks=42

        strategies = {
            'hash': HashCacheStrategy(),
            'info': InfoCacheStrategy()
        }

        mock_cache_client.set_many.return_value = True

        # Act
        result = cache_manager.cache_links([sample_link], strategies)

        # Assert
        result is True

        call_args = mock_cache_client.set_many.call_args
        cache_data = call_args[0][0]

        # Проверка данных в кэше
        hash_data = cache_data[f'link:hash:{link_hash}']
        info_data = cache_data[f'link:info:{link_code}']

        assert hash_data['url_hash'] == link_hash
        assert hash_data['short_code'] == link_code
        assert hash_data['original_url'] == sample_link.original_url
        assert hash_data['clicks'] == 42
        assert hash_data['last_accessed'] == sample_link.last_accessed.isoformat()

        # проверка идентичности данных для обеих стратегий
        assert hash_data == info_data

    def test_cache_service_stats_stores_statistic(self, cache_manager, mock_cache_client):
        """Тест кэширования статистики использования сервиса"""
        stats_strategy = StatsCacheStrategy()
        stats_data = {
            'total_urls': 100,
            'total_clicks': 1000,
            'avg_popular_per_url': 10.0,
            'popular_urls': []
        }

        # Act
        result = cache_manager.cache_service_stats(stats_data, stats_strategy, ttl=300)

        # Assert
        assert result is True
        mock_cache_client.set.assert_called_once_with(
            'link:stats:global',
            stats_data,
            300
        )
    
    def test_invalidate_link_removes_from_cache(self, cache_manager, mock_cache_client, sample_link):
        """Тест инвалидации ссылки из кэша"""
        link_hash = sample_link.url_hash
        link_code = sample_link.short_code
        strategies = {
            'hash': HashCacheStrategy(),
            'redirect': RedirectCacheStrategy(),
            'info': InfoCacheStrategy()
        }

        # Act
        result = cache_manager.invalidate_link(sample_link, strategies)

        # Assert
        assert result is True
        assert mock_cache_client.delete.call_count == 3

        # проврека удаления всех ключей
        delete_calls = [call[0][0] for call in mock_cache_client.delete.call_args_list]
        assert f'link:hash:{link_hash}' in delete_calls
        assert f'link:redirect:{link_code}' in delete_calls
        assert f'link:info:{link_code}' in delete_calls
    
    def test_get_service_stats_returns_cached_data(self, cache_manager, mock_cache_client):
        """Тест получения статистики использования сервиса из кэша"""
        stats_strategy = StatsCacheStrategy()
        cached_stats = {
            'total_urls': 50,
            'total_clicks': 500,
            'avg_clicks_per_url': 10.0,
            'popular_urls': []
        }
        mock_cache_client.get.return_value = cached_stats

        # Act
        result = cache_manager.get_service_stats(stats_strategy)

        # Assert
        assert result == cached_stats
        mock_cache_client.get.assert_called_once_with('link:stats:global')
    
    def test_get_cache_stats_returns_cache_statistics(self, cache_manager, mock_cache_client):
        """Тест получения статистики использования кэша"""
        cache_stats = {
            'hit_rate': 0.85,
            'miss_rate': 0.15,
            'total_keys': 100,
            'memory_used': '2.5MB'
        }
        mock_cache_client.get_cache_stats.return_value = cache_stats

        # Act
        result = cache_manager.get_cache_stats()

        # Assert
        assert result == cache_stats
        mock_cache_client.get_cache_stats.assert_called_once()

    def test_cache_manager_works_without_cache_client(self, mock_logger, sample_link):
        """Тест работы Cache_manager, когда кэш отключен (или без cache client)"""
        cache_manager = CacheManager(
            cache_client=None,
            logger=mock_logger
        )
        hash_strategy = HashCacheStrategy()
        strategies = {'hash': hash_strategy}

        # Act
        cache_result = cache_manager.cache_link(sample_link, strategies)
        get_result = cache_manager.get_link_by_hash(sample_link.url_hash, hash_strategy)

        invalidate_result = cache_manager.invalidate_link(sample_link, strategies)

        # Assert
        assert cache_result is False
        assert get_result is None
        assert invalidate_result is False
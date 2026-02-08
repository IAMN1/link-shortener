import pytest

from src.link_shortener.domain.value_objects.cache_strategy import HashCacheStrategy, InfoCacheStrategy, RedirectCacheStrategy, StatsCacheStrategy


@pytest.mark.unit
class TestCacheStrategy:
    """Тесты стратегий формирования ключей кэша"""

    def test_hash_cache_strategy_generates_correct_key(self):
        """Тест генерации ключа для хэш-стратегии"""
        strategy = HashCacheStrategy(prefix='test:hash:')

        # Act
        key = strategy.get_key('hash123')

        # Assert
        assert key == 'test:hash:hash123'
    
    def test_redirect_cache_strategy_generates_correct_key(self):
        """тест генерации ключа для редирект-стратегии"""
        strategy = RedirectCacheStrategy(prefix='test:redirect:')

        # Act
        key = strategy.get_key('code123')

        # Assert
        assert key == 'test:redirect:code123'
    
    def test_info_cache_strategy_generates_correct_key(self):
        """Тест генерации ключа для инфо-стратегии"""
        strategy = InfoCacheStrategy(prefix='test:info:')

        # Act
        key = strategy.get_key('code123')

        # Assert
        assert key == 'test:info:code123'
    
    def test_stats_cache_strategy_generates_correct_key(self):
        """Тест генерации ключа для статистики всего сервиса"""
        strategy = StatsCacheStrategy(prefix='test:stats:')

        # Act
        key = strategy.get_key()

        # Assert
        assert key == 'test:stats:global'
    
    def test_cache_strategies_have_different_prefixes(self):
        """Тест различных префиксов стретегий"""
        hash_strategy = HashCacheStrategy()
        redirect_strategy = RedirectCacheStrategy()
        info_strategy = InfoCacheStrategy()
        stats_strategy = StatsCacheStrategy()

        # Act
        hash_key = hash_strategy.get_key('test')
        redirect_key = redirect_strategy.get_key('test')
        info_key = info_strategy.get_key('test')
        stats_key = stats_strategy.get_key()

        # Assert
        assert hash_key.startswith('link:hash:')
        assert redirect_key.startswith('link:redirect:')
        assert info_key.startswith('link:info:')
        assert stats_key.startswith('link:stats:')
        assert hash_key != redirect_key
        assert redirect_key != info_key
        assert info_key != hash_key

    def test_custom_prefixes_work_correctly(self):
        """Тест работы с катомными префиксами"""
        
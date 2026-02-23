import json
import time
from unittest.mock import Mock
from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.url_hash import UrlHash
from link_shortener.infrastructure.cache.redis_cache import Link, RedisLinkCache
import pytest
import redis


@pytest.fixture
def redis_cache(mock_redis_client, monkeypatch):
    """Provide a RedisLinkCache instance with mocked Redis client."""

    monkeypatch.setattr("redis.from_url", lambda *args, **kwargs: mock_redis_client)

    cache = RedisLinkCache(
        "redis://localhost:6379/0", 
        link_ttl=3600, 
        stats_ttl=300, 
        prefix="link_shortener"
    )

    return cache


# ------------------------------------------------------------------
# TestRedisLinkCache
# ------------------------------------------------------------------
class TestRedisLinkCache:
    """Tests for RedisLinkCache."""

    # =============== General методы =============================
    def test_get_cache_info(self, redis_cache, mock_redis_client):
        """Should return cache info from Redis."""

        # Arrange
        mock_redis_client.info.return_value = {
            'used_memory_human': '1M',
            'connected_clients': 1,
            'uptime_in_seconds': 100,
            'keyspace_hits': 10,
            'keyspace_misses': 2,
        }

        # Act
        info = redis_cache.get_cache_info()

        # Assert
        assert info['used_memory'] == '1M'
        assert info['connected_clients'] == 1

    def test_delete_nonexistent(self, redis_cache, mock_redis_client):
        """Should not raise error when deleting non-existent short code."""

        # Arrange
        short_code = ShortCode('abc123')
        mock_redis_client.get.return_value = None

        # Act
        redis_cache.delete(short_code)
        
        # Assert
        code_key = redis_cache.key_gen.for_short_code(short_code.value)
        redirect_key = redis_cache.key_gen.for_redirect(short_code.value)
        mock_redis_client.get.assert_called_once_with(code_key)
        mock_redis_client.delete.assert_called_once_with(code_key, redirect_key)

    def test_delete_existing(self, redis_cache, mock_redis_client, sample_link):
        """Should delete all keys associated with a link."""

        # Arrange
        short_code = sample_link.short_code
        serialized = redis_cache._serialize(sample_link)
        mock_redis_client.get.return_value = serialized
        
        # Act
        redis_cache.delete(short_code)
        
        # Assert
        code_key = redis_cache.key_gen.for_short_code(short_code.value)
        redirect_key = redis_cache.key_gen.for_redirect(short_code.value)
        hash_key = redis_cache.key_gen.for_url_hash(sample_link.url_hash.value)
        mock_redis_client.get.assert_called_once_with(code_key)
        mock_redis_client.delete.assert_called_once_with(code_key, redirect_key, hash_key)

    def test_reconnect_after_interval(self, monkeypatch, mock_redis_client):
        """Should attempt to reconnect after retry interval."""

        # Arrange
        mock_from_url = Mock(return_value=mock_redis_client)
        monkeypatch.setattr(redis, "from_url", mock_from_url)

        cache = RedisLinkCache(
            "redis://localhost", 
            prefix="test", 
            link_ttl=3600, 
            stats_ttl=300
        )
        assert cache._available is True
        assert mock_from_url.call_count == 1

        # Вызов ошибки
        mock_redis_client.get.side_effect = redis.RedisError
        mock_redis_client.ping.side_effect = redis.RedisError

        cache.get_by_code(ShortCode("abc123"))
        assert cache._available is False

        # Перемещение времени вперед
        cache._last_attempt = time.time() - 20 # > retry_interval (10)

        # Убираем ошибки, подготавливаем успешное соединение
        mock_redis_client.get.side_effect = None
        mock_redis_client.ping.side_effect = None

        # Следующий вызов должен переподключиться
        cache.get_by_code(ShortCode("abc123"))
        assert cache._available is True
        assert mock_from_url.call_count == 2

    # =============== LinkCache методы =============================
    def test_get_by_code(self, redis_cache, mock_redis_client, sample_link):
        """Should retrieve a link by short code."""

        # Arrange
        serialized = redis_cache._serialize(sample_link)
        mock_redis_client.get.return_value = serialized

        # Act
        result = redis_cache.get_by_code(sample_link.short_code)

        # Assert
        assert result == sample_link
        mock_redis_client.get.assert_called_once_with(
            redis_cache.key_gen.for_short_code(
                sample_link.short_code.value
            )
        )

    def test_get_by_code_not_found(self, mock_redis_client, redis_cache):
        """Should return None when link not found in cache."""
        
        # Arrange
        mock_redis_client.get.return_value = None
        
        # Act
        result = redis_cache.get_by_code(ShortCode("abc123"))
        
        # Assert
        assert result is None

    def test_get_by_code_corrupted_data(self, redis_cache, mock_redis_client):
        """Should return None when cached data is corrupted."""
        
        # Arrange
        short_code = ShortCode('abc123')
        mock_redis_client.get.return_value = b'not a valid json'

        # Act
        result = redis_cache.get_by_code(short_code)

        # Assert
        assert result is None
    
    def test_get_by_code_redis_error(self, redis_cache, mock_redis_client):
        """Should return None and mark unavailable on Redis error."""

        # Arrange
        mock_redis_client.get.side_effect = redis.RedisError("Connection error")

        # Act
        result = redis_cache.get_by_code(ShortCode("abc123"))

        # Assert
        assert result is None
        assert redis_cache._available is False

    def test_get_by_hash(self, redis_cache, mock_redis_client, sample_link):
        """Should retrieve a link by URL hash."""

        serialized = redis_cache._serialize(sample_link)
        mock_redis_client.get.return_value = serialized

        # Act
        result = redis_cache.get_by_hash(sample_link.url_hash)

        # Assert
        assert result == sample_link
        mock_redis_client.get.assert_called_once_with(
            redis_cache.key_gen.for_url_hash(sample_link.url_hash.value)
        )

    def test_get_by_hashes_all_found(
        self, redis_cache, mock_redis_client, sample_link
    ):
        """
        Should retrieve multiple links by 
        their hashes when all are present.
        """
        
        # Arrange
        hash1 = sample_link.url_hash
        hash2 = UrlHash('b' * 64)
        link2 = Link.create(
            url_hash=hash2,
            short_code=ShortCode('xyz789'),
            original_url=OriginalUrl('https://example2.com')
        )

        serialized1 = redis_cache._serialize(sample_link)
        serialized2 = redis_cache._serialize(link2)
        # MGET возвращает список в том же порядке, что и ключи
        mock_redis_client.mget.return_value = [serialized1, serialized2]

        # Act
        result = redis_cache.get_by_hashes([hash1, hash2])

        # Assert
        assert result[hash1] == sample_link
        assert result[hash2] == link2
        expected_keys = [
            redis_cache.key_gen.for_url_hash(hash1.value),
            redis_cache.key_gen.for_url_hash(hash2.value),
        ]
        mock_redis_client.mget.assert_called_once_with(expected_keys)

    def test_get_by_hashes_partial_miss(self, redis_cache, mock_redis_client, sample_link):
        """Should return None for missing hashes when retrieving multiple."""
        hash1 = sample_link.url_hash
        hash2 = UrlHash('b' * 64)
        serialized = redis_cache._serialize(sample_link)
        mock_redis_client.mget.return_value = [serialized, None]

        result = redis_cache.get_by_hashes([hash1, hash2])

        assert result[hash1] == sample_link
        assert result[hash2] is None

    def test_save(self, redis_cache, mock_redis_client, sample_link):
        """Should save link on all cache levels."""

        # Arrange & Act
        pipeline = mock_redis_client.pipeline.return_value
        pipeline.setex.return_value = pipeline
        
        # Act
        redis_cache.save(sample_link)

        # Assert
        assert pipeline.setex.call_count == 3
        pipeline.execute.assert_called_once()
    
    def test_save_many(self, redis_cache, mock_redis_client, sample_link):
        """Should save multiple links at once."""
        
        # Arrange
        mock_pipeline = mock_redis_client.pipeline.return_value
        mock_pipeline.setex.return_value = mock_pipeline

        # Act
        redis_cache.save_many([sample_link])

        # Assert
        assert mock_pipeline.setex.call_count == 3
        mock_pipeline.execute.assert_called_once()

    def test_save_many_empty(self, redis_cache, mock_redis_client):
        """Should not call pipeline when saving empty list."""
        redis_cache.save_many([])
        mock_redis_client.pipeline.assert_not_called()

    # =============== RedirectCache методы =============================
    def test_get_original_url(self, redis_cache, mock_redis_client):
        """Should retrieve original URL from L1 cache."""

        # Arrange
        short_code = ShortCode("abc123")
        expected_url = "https://test.com"
        mock_redis_client.get.return_value = expected_url.encode()

        # Act
        result = redis_cache.get_original_url(short_code)

        # Assert
        assert result == expected_url
        mock_redis_client.get.assert_called_once_with(
            redis_cache.key_gen.for_redirect(short_code.value)
        )

    def test_save_original_url_and_get(self, redis_cache, mock_redis_client):
        """Should save original URL and retrieve it."""

        # Arrange
        short_code = ShortCode('abc123')
        url = 'https://test.com'
        key = redis_cache.key_gen.for_redirect(short_code.value)
        mock_redis_client.get.return_value = url.encode()

        # Acts
        redis_cache.save_original_url(short_code, url)
        result = redis_cache.get_original_url(short_code)

        # Assrets
        mock_redis_client.setex.assert_called_once_with(key, redis_cache.ttl, url)
        mock_redis_client.get.assert_called_once_with(key)
        assert result == url
    
    # =============== StatsCache методы =============================
    def test_stats(self, redis_cache, mock_redis_client):
        """Should save and retrieve stats."""

        # Arrange & Act
        stats = {"total": 10}
        redis_cache.save_stats(stats)
        
        # Assert
        mock_redis_client.setex.assert_called_once()
        # Проверка получение статистики
        mock_redis_client.get.return_value = json.dumps(stats).encode()
        assert redis_cache.get_stats() == stats

    def test_get_stats_none(self, redis_cache, mock_redis_client):
        """Should return None when stats not found."""

        mock_redis_client.get.return_value = None
        assert redis_cache.get_stats() is None
    
    def test_delete_stats(self, redis_cache, mock_redis_client):
        """Should delete stats key."""
        
        # Arrange
        key = redis_cache.key_gen.for_stats()
        
        # Act
        redis_cache.delete_stats()
        
        # Assert
        mock_redis_client.delete.assert_called_once_with(key)
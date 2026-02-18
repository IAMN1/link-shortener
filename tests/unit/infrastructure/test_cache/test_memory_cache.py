import time
from link_shortener.domain.entities.link import Link
from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.url_hash import UrlHash
from link_shortener.infrastructure.cache.memory_cache import InMemoryLinkCache
import pytest


@pytest.fixture
def memory_cache():
    """Provide an InMemoryLinkCache instance with short TTL for testing."""

    return InMemoryLinkCache(link_ttl=1, stats_ttl=1, prefix="test")


# ------------------------------------------------------------------
# TestInMemoryLinkCache
# ------------------------------------------------------------------
class TestInMemoryLinkCache:
    """Tests for InMemoryLinkCache."""

    # =============== General методы =============================
    def test_ttl_expiration(self, memory_cache, sample_link, monkeypatch):
        """Should expire cache entries after TTL."""

        # Arrange
        fake_time = 1_000.0
        monkeypatch.setattr(time, 'time', lambda: fake_time)
        memory_cache.save(sample_link)
        
        # Act & Assert

        # Данные доступны
        assert memory_cache.get_by_hash(sample_link.url_hash) == sample_link
        
        # перемещение времени вперед на TTL + 1
        fake_time += memory_cache.link_ttl + 1
        # Данные уже не доступны
        assert memory_cache.get_by_hash(sample_link.url_hash) is None
        assert memory_cache.get_by_code(sample_link.short_code) is None
        assert memory_cache.get_original_url(sample_link.short_code) is None

    def test_delete(self, memory_cache, sample_link):
        """Should delete all data associated with a short code."""
        
        # Arrange
        memory_cache.save(sample_link)
        
        # Act
        memory_cache.delete(sample_link.short_code)

        # Assert
        assert memory_cache.get_by_hash(sample_link.url_hash) is None
        assert memory_cache.get_by_code(sample_link.short_code) is None
        assert memory_cache.get_original_url(sample_link.short_code) is None

    def test_save_many(
        self, memory_cache, sample_link
    ):
        """Should save multiple links at once."""
        
        # Arrange
        link2 = Link.create(
            url_hash=UrlHash("b"*64),
            short_code=ShortCode("xyz789"),
            original_url=OriginalUrl("https://example2.com")
        )

        # Act
        memory_cache.save_many([sample_link, link2])

        # Assert
        assert memory_cache.get_by_code(sample_link.short_code) == sample_link
        assert memory_cache.get_by_code(link2.short_code) == link2

    def test_get_cache_info(self, memory_cache, sample_link):
        """Should return correct cache info."""
        
        # Arrange
        memory_cache.save(sample_link)

        # Act
        info = memory_cache.get_cache_info()

        # Assert
        assert info["link_count"] == 2 # сохранено по двум ключам
        assert info["redirect_count"] == 1
        assert info["has_stats"] is False
        assert info["total_keys"] == 3

    def test_get_cache_info_after_expiry(self, memory_cache, sample_link):
        """Should exclude expired entries from cache info."""

        memory_cache.save(sample_link)
        # принудительно протухаем
        for key in list(memory_cache._expiry.keys()):
            memory_cache._expiry[key] = time.time() - 10
        info = memory_cache.get_cache_info()
        assert info['link_count'] == 0
        assert info['redirect_count'] == 0
        assert info['total_keys'] == 0

    def test_delete_nonexistent(self, memory_cache):
        """Should not raise error when deleting non-existent short code."""

        short_code = ShortCode("abc123")
        memory_cache.delete(short_code) # не должно совпадать

    def test_save_duplicate(self, memory_cache, sample_link):
        """Should overwrite existing entry when saving same link again."""
        
        # Arrange
        memory_cache.save(sample_link)
        sample_link.clicks = 5
        memory_cache.save(sample_link)
        
        # Act
        retrieved = memory_cache.get_by_code(sample_link.short_code)
        
        # Assert
        assert retrieved.clicks == 5

    def test_clean_expired_manual(self, memory_cache, sample_link):
        """Should manually clean expired entries."""
        
        # Arrange
        memory_cache.save(sample_link)
        key = memory_cache.key_gen.for_short_code(sample_link.short_code.value)
        memory_cache._expiry[key] = time.time() - 10  # истек
        
        # Act
        memory_cache._clean_expired('code')
        
        # Assert
        assert memory_cache.get_by_code(sample_link.short_code) is None

    # =============== LinkCache методы =============================
    def test_get_by_code(self, memory_cache, sample_link):
        """Should retrieve a link by its short code."""

        # Arrange
        memory_cache.save(sample_link)
        
        # Act
        retrieved = memory_cache.get_by_code(sample_link.short_code)

        # Assert
        assert retrieved == sample_link
    
    def test_get_by_hash(self, memory_cache, sample_link):
        """Should retrieve a link by its URL hash."""

        # Arrange
        memory_cache.save(sample_link)
        
        # Act
        retrieved = memory_cache.get_by_hash(sample_link.url_hash)
        
        # Assert
        assert retrieved == sample_link

    def test_get_by_hashes(self, memory_cache, sample_link):
        """
        Should retrieve multiple links by their hashes.
        """

        # Arragne
        memory_cache.save(sample_link)
        
        # Act
        result = memory_cache.get_by_hashes([sample_link.url_hash])
        
        # Assert
        assert result[sample_link.url_hash] == sample_link

    def test_get_by_hashes_empty(self, memory_cache):
        """Should return empty dict when given empty list of hashes."""
        result = memory_cache.get_by_hashes([])
        assert result == {}

    # =============== RedirectCache методы =============================
    def test_get_original_url(self, memory_cache, sample_link):
        """Should retrieve original URL for redirect."""
        
        # Arrage
        memory_cache.save(sample_link)
        
        # Act
        url = memory_cache.get_original_url(sample_link.short_code)
        
        # Assert
        assert url == sample_link.original_url.value
    
    def test_save_original_url_direct(self, memory_cache, sample_link):
        """Should save original URL directly and retrieve it from L1 cache."""

        # Arrange
        memory_cache.save_original_url(sample_link.short_code, sample_link.original_url.value)
        
        # Act
        url = memory_cache.get_original_url(sample_link.short_code)
        
        # Assert
        assert url == sample_link.original_url.value
    

    # =============== StatsCache методы =============================
    def test_stats_cache(self, memory_cache):
        """Should save, retrieve, and delete stats correctly."""

        # Arrange
        stats = {"total": 10}
        
        # Act
        memory_cache.save_stats(stats)

        # Assert
        assert memory_cache.get_stats() == stats
        memory_cache.delete_stats()
        assert memory_cache.get_stats() is None


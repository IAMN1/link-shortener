import time
from link_shortener.domain.entities.link import Link
from link_shortener.domain.value_objects.dedup_scope import DedupScope
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

    # =============== General methods =============================
    def test_ttl_expiration(self, memory_cache, sample_link, monkeypatch):
        """Should expire cache entries after TTL."""

        # Arrange
        fake_time = 1_000.0
        monkeypatch.setattr(time, 'time', lambda: fake_time)
        memory_cache.save(sample_link)
        
        # Act & Assert

        # Data is available
        assert memory_cache.get_by_hash(sample_link.url_hash, sample_link.dedup_scope()) == sample_link
        
        # advance time past TTL + 1
        fake_time += memory_cache.link_ttl + 1
        # Data is no longer available
        assert memory_cache.get_by_hash(sample_link.url_hash, sample_link.dedup_scope()) is None
        assert memory_cache.get_by_code(sample_link.short_code) is None
        assert memory_cache.get_redirect(sample_link.short_code) is None

    def test_delete(self, memory_cache, sample_link):
        """Should delete all data associated with a short code."""
        
        # Arrange
        memory_cache.save(sample_link)
        
        # Act
        memory_cache.delete(sample_link)

        # Assert
        assert memory_cache.get_by_hash(sample_link.url_hash, sample_link.dedup_scope()) is None
        assert memory_cache.get_by_code(sample_link.short_code) is None
        assert memory_cache.get_redirect(sample_link.short_code) is None

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
        assert info["link_count"] == 2  # stored under two keys
        assert info["redirect_count"] == 1
        assert info["has_stats"] is False
        assert info["total_keys"] == 3

    def test_get_cache_info_after_expiry(self, memory_cache, sample_link):
        """Should exclude expired entries from cache info."""

        memory_cache.save(sample_link)
        # force expiry
        for key in list(memory_cache._expiry.keys()):
            memory_cache._expiry[key] = time.time() - 10
        info = memory_cache.get_cache_info()
        assert info['link_count'] == 0
        assert info['redirect_count'] == 0
        assert info['total_keys'] == 0

    def test_expired_statistics_are_gone_from_the_report_too(
        self, memory_cache
    ):
        """The report must not say it holds what it no longer holds.

        The statistics live in a field of their own rather than in one of
        the dictionaries, so the sweep that drops their key does not drop
        them. It was written to, in a branch placed after the loop that
        had already deleted that key -- so the branch could not run, and
        ``get_cache_info`` answered ``has_stats: True`` beside
        ``total_keys: 0`` until something called ``get_stats``.

        Asked of ``get_cache_info`` alone, because ``get_stats`` clears
        them on its way past and would answer this question for it.
        """
        memory_cache.save_stats({"total_links": 7})
        assert memory_cache.get_cache_info()["has_stats"] is True

        for key in list(memory_cache._expiry.keys()):
            memory_cache._expiry[key] = time.time() - 10

        info = memory_cache.get_cache_info()

        assert info["has_stats"] is False
        assert info["total_keys"] == 0

    def test_delete_nonexistent(self, memory_cache, sample_link):
        """Should not raise error when deleting a link that was never cached."""

        memory_cache.delete(sample_link)  # should not fail

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
        memory_cache._expiry[key] = time.time() - 10  # expired
        
        # Act
        memory_cache._clean_expired()
        
        # Assert
        assert memory_cache.get_by_code(sample_link.short_code) is None

    # =============== LinkCache methods =============================
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
        retrieved = memory_cache.get_by_hash(sample_link.url_hash, sample_link.dedup_scope())
        
        # Assert
        assert retrieved == sample_link

    def test_get_by_hashes(self, memory_cache, sample_link):
        """
        Should retrieve multiple links by their hashes.
        """

        # Arragne
        memory_cache.save(sample_link)
        
        # Act
        result = memory_cache.get_by_hashes([sample_link.url_hash], sample_link.dedup_scope())
        
        # Assert
        assert result[sample_link.url_hash] == sample_link

    def test_get_by_hashes_empty(self, memory_cache):
        """Should return empty dict when given empty list of hashes."""
        result = memory_cache.get_by_hashes([], DedupScope())
        assert result == {}

    # =============== RedirectCache methods =============================
    def test_get_redirect(self, memory_cache, sample_link):
        """Should retrieve the redirect entry for a short code."""

        # Arrage
        memory_cache.save(sample_link)

        # Act
        entry = memory_cache.get_redirect(sample_link.short_code)

        # Assert
        assert entry.original_url == sample_link.original_url.value
        # The entry has to answer the expiry question on its own, otherwise
        # an L1 hit cannot complete a redirect.
        assert entry.expires_at == sample_link.expires_at

    def test_save_redirect_direct(self, memory_cache, sample_link):
        """Should save a redirect directly and retrieve it from L1 cache."""

        # Arrange
        memory_cache.save_redirect(
            sample_link.short_code, sample_link.original_url.value
        )

        # Act
        entry = memory_cache.get_redirect(sample_link.short_code)

        # Assert
        assert entry.original_url == sample_link.original_url.value

    def test_an_expired_link_is_not_served_from_l1(self, memory_cache, sample_link):
        """An entry must never outlive the link it points at."""
        from datetime import datetime, timedelta, timezone

        memory_cache.save_redirect(
            sample_link.short_code,
            sample_link.original_url.value,
            datetime.now(timezone.utc) - timedelta(seconds=1),
        )

        assert memory_cache.get_redirect(sample_link.short_code) is None
    

    # =============== StatsCache methods =============================
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


from link_shortener.infrastructure.cache.cache_key_generator import CacheKeyGenerator


# ------------------------------------------------------------------
# TestCacheKeyGenerator
# ------------------------------------------------------------------
class TestCacheKeyGenerator:
    """Tests for CacheKeyGenerator."""

    def test_cache_key_generator_default_prefix(self):
        """Should generate keys with default prefix when no prefix provided."""
        
        # Act
        gen = CacheKeyGenerator() # default prefix = "link_shortener"

        # Assert
        assert gen.for_redirect("abc123") == "link_shortener:redirect:abc123"
        assert gen.for_short_code("abc123") == "link_shortener:code:abc123"
        assert gen.for_url_hash("hash") == "link_shortener:hash:hash"
        assert gen.for_stats() == "link_shortener:stats:global"
    
    def test_cache_key_generator_custom_prefix(self):
        """Should generate keys with custom prefix when provided."""
        
        gen = CacheKeyGenerator(prefix="test")
        
        assert gen.for_redirect("xyz") == "test:redirect:xyz"
        assert gen.for_short_code("abc123") == "test:code:abc123"
        assert gen.for_url_hash("hash") == "test:hash:hash"
        assert gen.for_stats() == "test:stats:global"

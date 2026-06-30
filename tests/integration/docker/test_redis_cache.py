"""
Level 2 integration tests: Redis cache against real Redis instance.
"""

import pytest
import time
from link_shortener.domain.value_objects.short_code import ShortCode


class TestRedisConnection:
    """Verify real Redis connection works."""

    def test_ping(self, redis_client):
        assert redis_client.ping() is True

    def test_set_get(self, redis_client):
        redis_client.set("test_key", "test_value", ex=10)
        value = redis_client.get("test_key")
        assert value == "test_value"
        redis_client.delete("test_key")

    def test_ttl_expiration(self, redis_client):
        redis_client.set("ttl_key", "expires", ex=1)
        assert redis_client.get("ttl_key") == "expires"
        time.sleep(1.1)
        assert redis_client.get("ttl_key") is None

    def test_delete(self, redis_client):
        redis_client.set("del_key", "to_delete", ex=10)
        redis_client.delete("del_key")
        assert redis_client.get("del_key") is None


class TestRedisCacheIntegration:
    """Test application cache layer against real Redis."""

    def test_cache_save_and_get_original_url(self, app):
        with app.app_context():
            cache = app.container.get_cache()
            code = ShortCode("redtest")
            cache.save_original_url(code, "https://cached.com")
            result = cache.get_original_url(code)
            assert result == "https://cached.com"

    def test_cache_delete_invalidates(self, app):
        with app.app_context():
            cache = app.container.get_cache()
            code = ShortCode("deltest")
            cache.save_original_url(code, "https://to-delete.com")
            cache.delete(code)
            result = cache.get_original_url(code)
            assert result is None

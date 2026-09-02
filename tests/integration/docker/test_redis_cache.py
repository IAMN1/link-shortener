"""
Level 2 integration tests: Redis cache against real Redis instance.
"""

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

    def test_cache_save_and_get_redirect(self, app):
        with app.app_context():
            cache = app.container.get_cache()
            code = ShortCode("redtest")
            cache.save_redirect(code, "https://cached.com")
            result = cache.get_redirect(code)
            assert result.original_url == "https://cached.com"

    def test_cache_delete_invalidates(self, app):
        with app.app_context():
            cache = app.container.get_cache()
            code = ShortCode("deltest")
            cache.save_redirect(code, "https://to-delete.com")
            cache.delete_redirect(code)
            result = cache.get_redirect(code)
            assert result is None

    def test_an_expired_link_is_not_served_from_l1(self, app):
        """Against a real Redis: the entry must not outlive the link."""
        from datetime import datetime, timedelta, timezone

        with app.app_context():
            cache = app.container.get_cache()
            code = ShortCode("exptest")
            cache.save_redirect(
                code,
                "https://expired.com",
                datetime.now(timezone.utc) - timedelta(seconds=1),
            )
            assert cache.get_redirect(code) is None

    def test_an_entry_from_the_old_format_ages_out_quietly(self, app):
        """Bare URL strings are still in live caches; they must not raise."""
        with app.app_context():
            cache = app.container.get_cache()
            code = ShortCode("oldfmt1")
            key = cache.key_gen.for_redirect(code.value)
            cache._client.set(
                key, "https://written-before-the-envelope.com", ex=60
            )

            # Unusable -- it carries no expiry, so its age cannot be judged.
            assert cache.get_redirect(code) is None

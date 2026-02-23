from unittest.mock import patch
from link_shortener.application.ports.cache.null_cache import NullCache
from link_shortener.application.ports.logger.null_audit import NullAuditLogger
from link_shortener.application.ports.logger.null_logger import NullLogger
from link_shortener.infrastructure.config.testing import TestingConfig
from link_shortener.infrastructure.core.audit_logger import StructlogAuditLogger
from link_shortener.infrastructure.logging.failover_logger import FailoverLogger
from link_shortener.web.dependency_injection import Container
import pytest


# Сохраняем оригинальные методы класса Container, чтобы при необходимости восстановить
_original_get_logger = Container.get_logger
_original_get_audit_logger = Container.get_audit_logger
_original_get_cache = Container.get_cache


class TestContainer:
    """Tests for dependency injection container."""

    @pytest.fixture
    def config(self):
        return TestingConfig()

    def test_get_logger_disabled(self, config, monkeypatch):
        """Logger should be NullLogger when logging is disabled."""
        monkeypatch.setattr(Container, "get_logger", _original_get_logger)
        config.LOGGING_ENABLED = False
        container = Container(config)
        assert isinstance(container.get_logger(), NullLogger)

    def test_get_logger_enabled(self, config, monkeypatch):
        """Logger should be FailoverLogger when logging is enabled."""
        monkeypatch.setattr(Container, "get_logger", _original_get_logger)
        config.LOGGING_ENABLED = True
        # Патчим классы логгеров по месту их использования в dependency_injection
        with patch('link_shortener.web.dependency_injection.StructLogger'), \
             patch('link_shortener.web.dependency_injection.StandartLogger'):
            container = Container(config)
            assert isinstance(container.get_logger(), FailoverLogger)

    def test_get_audit_logger_disabled(self, config, monkeypatch):
        """Audit logger should be NullAuditLogger when audit is disabled."""
        monkeypatch.setattr(Container, "get_audit_logger", _original_get_audit_logger)
        config.AUDIT_ENABLED = False
        container = Container(config)
        assert isinstance(container.get_audit_logger(), NullAuditLogger)

    def test_get_audit_logger_enabled(self, config, monkeypatch):
        """Audit logger should be StructlogAuditLogger when audit is enabled."""
        monkeypatch.setattr(Container, "get_audit_logger", _original_get_audit_logger)
        config.AUDIT_ENABLED = True
        container = Container(config)
        assert isinstance(container.get_audit_logger(), StructlogAuditLogger)

    def test_get_cache_disabled(self, config, monkeypatch):
        """Cache should be NullCache when caching is disabled."""
        monkeypatch.setattr(Container, "get_cache", _original_get_cache)
        config.CACHE_ENABLED = False
        container = Container(config)
        assert isinstance(container.get_cache(), NullCache)

    def test_get_cache_redis_enabled(self, config, monkeypatch):
        """Cache should be RedisLinkCache when Redis is enabled."""
        monkeypatch.setattr(Container, "get_cache", _original_get_cache)
        config.CACHE_ENABLED = True
        config.REDIS_ENABLED = True
        # Патчим RedisLinkCache по месту использования в dependency_injection
        with patch('link_shortener.web.dependency_injection.RedisLinkCache') as mock_redis:
            container = Container(config)
            cache = container.get_cache()
            mock_redis.assert_called_once_with(
                redis_url=config.REDIS_URL,
                prefix=config.CACHE_LINK_PREFIX,
                link_ttl=config.CACHE_LINK_TTL,
                stats_ttl=config.CACHE_STATS_TTL
            )
            assert cache is mock_redis.return_value

    def test_get_cache_redis_failure_fallback_to_null(self, config, monkeypatch):
        """Cache should fall back to NullCache if Redis initialization fails."""
        monkeypatch.setattr(Container, "get_cache", _original_get_cache)
        config.CACHE_ENABLED = True
        config.REDIS_ENABLED = True
        # Патчим с side_effect, чтобы конструктор выбросил исключение
        with patch('link_shortener.web.dependency_injection.RedisLinkCache', side_effect=Exception("fail")):
            container = Container(config)
            assert isinstance(container.get_cache(), NullCache)

    def test_get_cache_memory_fallback(self, config, monkeypatch):
        """Cache should be InMemoryLinkCache when Redis is disabled."""
        monkeypatch.setattr(Container, "get_cache", _original_get_cache)
        config.CACHE_ENABLED = True
        config.REDIS_ENABLED = False
        with patch('link_shortener.web.dependency_injection.InMemoryLinkCache') as mock_memory:
            container = Container(config)
            cache = container.get_cache()
            mock_memory.assert_called_once_with(
                prefix=config.CACHE_LINK_PREFIX,
                link_ttl=config.CACHE_LINK_TTL,
                stats_ttl=config.CACHE_STATS_TTL
            )
            assert cache is mock_memory.return_value

    def test_use_cases_are_singletons(self, config, monkeypatch):
        """Each use case should be created only once (singleton within container)."""
        # Восстанавливаем оригинальные методы для чистоты эксперимента
        monkeypatch.setattr(Container, "get_logger", _original_get_logger)
        monkeypatch.setattr(Container, "get_audit_logger", _original_get_audit_logger)
        monkeypatch.setattr(Container, "get_cache", _original_get_cache)
        container = Container(config)
        uc1 = container.get_create_short_link_use_case()
        uc2 = container.get_create_short_link_use_case()
        assert uc1 is uc2
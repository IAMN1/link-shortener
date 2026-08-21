from unittest.mock import Mock
from link_shortener.infrastructure.cache.null_cache import NullCache
from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.infrastructure.di.container import Container
import pytest


class TestContainer:
    """Tests for dependency injection container."""

    @pytest.fixture
    def config(self):
        return TestingConfig()

    def test_container_creates_with_config(self, config):
        """Container should initialize with a valid config."""
        container = Container(config)
        assert container.config is config

    def test_the_audit_logger_it_hands_out_is_the_counting_one(self, config):
        """The accessor and the use cases must get the same object.

        It handed back the component's logger directly, so anything wired
        through here wrote to ``audit.log`` and was counted nowhere.
        Measured on the running stack the day the error handler became its
        first caller: two ``PERMISSION_DENIED`` lines in the journal and
        no row in ``security_events``, so the chart on the journal page
        reported no refusals while the journal beside it listed two.
        """
        from link_shortener.infrastructure.logging.handlers.audit.counting import (
            CountingAuditLogger,
        )

        container = Container(config)

        assert isinstance(container.get_audit_logger(), CountingAuditLogger)

    def test_get_link_service(self, config):
        """Container should provide a LinkService instance."""
        container = Container(config)
        from link_shortener.application.facades.link_service import LinkService
        assert isinstance(container.get_link_service(), LinkService)

    def test_get_admin_service(self, config):
        """Container should provide an AdminService instance."""
        container = Container(config)
        admin = container.get_admin_service()
        assert admin is not None

    def test_get_cache_disabled(self, config):
        """Cache should be NullCache when Redis is disabled."""
        config.REDIS_ENABLED = False
        config.CACHE_ENABLED = False
        from link_shortener.infrastructure.di.components.cache import CacheComponent
        cache_component = CacheComponent(
            cache_enabled=False,
            redis_enabled=False,
            redis_url="",
            link_prefix="link",
            link_ttl=300,
            stats_ttl=60,
            connect_timeout=2,
            socket_timeout=2,
            retry_interval=10,
            logger=Mock(),
            secret_key="di-test-secret",
        )
        cache = cache_component.get_cache()
        assert isinstance(cache, NullCache)

    def test_get_rate_limiter(self, config):
        """Container should provide a rate limiter."""
        container = Container(config)
        rate_limiter = container.get_rate_limiter()
        assert rate_limiter is not None

    def test_get_authentication_service(self, config):
        """Container should provide an authentication service."""
        container = Container(config)
        auth_service = container.get_authentication_service()
        assert auth_service is not None

    def test_get_authorization_service(self, config):
        """Container should provide an authorization service."""
        container = Container(config)
        auth_service = container.get_authorization_service()
        assert auth_service is not None

    def test_get_uow_factory(self, config):
        """Container should provide a UoW factory callable."""
        container = Container(config)
        factory = container.get_uow_factory()
        assert callable(factory)

    def test_use_cases_are_created(self, config):
        """Use case accessors should return non-None instances."""
        container = Container(config)
        uc = container.get_create_short_link_use_case()
        assert uc is not None

    def test_close_does_not_raise(self, config):
        """Container close() should not raise."""
        container = Container(config)
        container.close()

from unittest.mock import MagicMock, Mock
from jinja2 import BaseLoader
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.facades.link_service import LinkService
from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.web.app_factory import create_app
from link_shortener.infrastructure.di.container import Container
import pytest


TEST_SECRET_KEY = "test-secret-key"
"""Signing key the web-layer tests build CSRF tokens with."""

TEST_USER_ID = "user-1"
"""Identity the mocked authentication service resolves every request to."""


class TestConfig(TestingConfig):
    """Simple config object for testing web layer."""
    TESTING = True
    DEBUG = False
    SECRET_KEY = TEST_SECRET_KEY
    SHORT_CODE_SECRET_PEPPER = "test-pepper"
    DATABASE_URL = "sqlite:///:memory:"
    REDIS_ENABLED = False
    CACHE_ENABLED = False
    LOGGING_ENABLED = False
    AUDIT_ENABLED = False
    BASE_URL = "http://testserver/"
    HOST = "testserver"
    PORT = 80
        


@pytest.fixture
def mock_link_service():
    """Provide a LinkService for testing"""
    mock = Mock(spec=LinkService)

    mock.create_short_link.return_value = MagicMock()
    mock.get_link_info.return_value = MagicMock()
    mock.batch_create_short_links.return_value = MagicMock()
    mock.get_service_stats.return_value = MagicMock()

    return mock

@pytest.fixture
def test_config():
    """Return a sample config dict for testing web layer"""
    return TestConfig()

class TestLogger(Logger):
    """
    Test logger that stores all messages in a list.
    Inherits from abstract Logger to guarantee all methods are present.
    """
    def __init__(self):
        super().__init__()
        self.messages = []  # each element: (level, message, kwargs)

    def debug(self, message, **kwargs):
        self.messages.append(('debug', message, kwargs))

    def info(self, message, **kwargs):
        self.messages.append(('info', message, kwargs))

    def warning(self, message, **kwargs):
        self.messages.append(('warning', message, kwargs))

    def error(self, message, **kwargs):
        self.messages.append(('error', message, kwargs))

    def exception(self, message, exc_info=None, **kwargs):
        # In test logger we ignore exc_info but record the call
        self.messages.append(('exception', message, kwargs))

    def is_healthy(self):
        return True

@pytest.fixture
def test_logger():
    """Fixture returning a TestLogger instance."""
    return TestLogger()

@pytest.fixture
def mock_auth_service():
    """
    Authentication service shared by the middlewares and the controllers.

    The real container hands out one instance, and the CSRF layer asks it
    who the request belongs to, so the tests need the same object the
    controller holds rather than a fresh mock per call site.
    """
    mock = Mock()
    mock.validate_token.return_value = {"sub": TEST_USER_ID, "type": "refresh"}
    return mock


@pytest.fixture
def app(test_config, mock_link_service, mock_auth_service, monkeypatch, test_logger):
    """
    Create a Flask app for testing with mocked services.
    """

    # Mock the Container class so create_app gets mock services
    original_init = Container.__init__

    def mock_init(self, config):
        original_init(self, config)

    # Override service accessors to return mocks
    monkeypatch.setattr(Container, "get_link_service", lambda self: mock_link_service)
    monkeypatch.setattr(Container, "get_admin_service", lambda self: Mock())
    monkeypatch.setattr(Container, "get_logger", lambda self, *a, **kw: test_logger)
    monkeypatch.setattr(Container, "get_active_logger_name", lambda self: "test")
    monkeypatch.setattr(
        Container, "get_authentication_service", lambda self: mock_auth_service
    )
    # WARNING: a bare Mock answers every is_allowed(...) with a truthy Mock,
    # so `@require_permission` in this module cannot refuse anyone. Nothing
    # here tests authorization, and a test that asserts 200 for an
    # unauthenticated request is asserting the mock, not the endpoint --
    # removing the decorator from every admin endpoint leaves this suite
    # green. Authorization is covered against the real service in
    # tests/integration/web/controllers/ (test_link_access.py,
    # test_admin_controller.py); put new access-control tests there.
    monkeypatch.setattr(Container, "get_authorization_service", lambda self: Mock())
    monkeypatch.setattr(Container, "get_uow_factory", lambda self: Mock())
    monkeypatch.setattr(Container, "get_rate_limiter", lambda self: Mock())
    monkeypatch.setattr(Container, "get_login_use_case", lambda self: Mock())
    monkeypatch.setattr(Container, "get_register_use_case", lambda self: Mock())
    monkeypatch.setattr(Container, "get_cache", lambda self: Mock(cache_type="null"))
    monkeypatch.setattr(Container, "get_db_manager", lambda self: MagicMock())
    monkeypatch.setattr(Container, "close", lambda self: None)

    app = create_app(config=test_config)
    return app

@pytest.fixture
def client(app):
    """Test client for the app."""
    return app.test_client()

class MockTemplateLoader(BaseLoader):
    def get_source(self, environment, template):
        # Return dummy source for any template
        return f"Rendered {template}", None, lambda: True

@pytest.fixture(autouse=True)
def mock_templates(app):
    app.jinja_env.loader = MockTemplateLoader()
    yield

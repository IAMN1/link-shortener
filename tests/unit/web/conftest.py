from unittest.mock import MagicMock, Mock
from jinja2 import BaseLoader
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.services.link_service import LinkService
from link_shortener.infrastructure.config.testing import TestingConfig
from link_shortener.web.app_factory import create_app
from link_shortener.web.dependency_injection import Container
import pytest


class TestConfig(TestingConfig):
    """Simple config object for testing web layer."""
    TESTING = True
    DEBUG = False
    SECRET_KEY = "test-secret-key"
    SHORT_CODE_SECRET_PEPPER = "test-pepper"
    DATABASE_URL = "sqlite:///:memory:"
    REDIS_ENABLED = False
    CACHE_ENABLED = False
    LOGGING_ENABLED = True
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
    Тестовый логгер, сохраняющий все сообщения в список.
    Наследуется от абстрактного Logger, чтобы гарантировать наличие всех методов.
    """
    def __init__(self):
        super().__init__()
        self.messages = []  # каждый элемент: (level, message, kwargs)

    def debug(self, message, **kwargs):
        self.messages.append(('debug', message, kwargs))

    def info(self, message, **kwargs):
        self.messages.append(('info', message, kwargs))

    def warning(self, message, **kwargs):
        self.messages.append(('warning', message, kwargs))

    def error(self, message, **kwargs):
        self.messages.append(('error', message, kwargs))

    def exception(self, message, exc_info=None, **kwargs):
        # В тестовом логгере игнорируем exc_info, но сохраняем вызов
        self.messages.append(('exception', message, kwargs))

@pytest.fixture
def test_logger():
    """Фикстура, возвращающая экземпляр TestLogger."""
    return TestLogger()

@pytest.fixture
def app(test_config, mock_link_service, monkeypatch, test_logger):
    """
    Create a Flask app for testing with mocked LinkService.
    We need to monkeypatch the Container.get_link_service method.
    """

    def mock_get_link_service(self):
        return mock_link_service
    
    monkeypatch.setattr(Container, "get_link_service", mock_get_link_service)
    monkeypatch.setattr(Container, "get_logger", lambda self: test_logger)

    # Подменяем все остальные методы контейнера, чтобы они возвращали моки
    monkeypatch.setattr(Container, "get_audit_logger", lambda self: Mock())
    monkeypatch.setattr(Container, "get_repository", lambda self: Mock())
    monkeypatch.setattr(Container, "get_cache", lambda self: Mock())
    monkeypatch.setattr(Container, "get_shortening_policy", lambda self: Mock())
    monkeypatch.setattr(Container, "get_db_manager", lambda self: Mock())

    app = create_app(config=test_config)
    return app

@pytest.fixture
def client(app):
    """Test client for the app."""
    return app.test_client()

class MockTemplateLoader(BaseLoader):
    def get_source(self, environment, template):
        # Возвращаем фиктивный источник для любого шаблона
        return f"Rendered {template}", None, lambda: True

@pytest.fixture(autouse=True)
def mock_templates(app):
    app.jinja_env.loader = MockTemplateLoader()
    yield

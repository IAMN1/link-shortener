from unittest.mock import Mock
from link_shortener.application.ports.cache.redirect_cache import RedirectCache
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
import pytest


@pytest.fixture
def mock_redirect_cache():
    """Provide a mock for RedirectCache."""
    return Mock(spec=RedirectCache)

@pytest.fixture
def mock_logger():
    """Provide a mock for Logger."""
    return Mock(spec=Logger)

@pytest.fixture
def mock_audit_logger():
    """Provide a mock for audit logger"""
    return Mock(spec=AuditLogger)

@pytest.fixture
def base_url():
    """Provide a base URL for short links."""
    return 'https://short.link'

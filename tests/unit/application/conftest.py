from unittest.mock import Mock
from link_shortener.application.ports.cache.link_cache import LinkCache
from link_shortener.application.ports.cache.link_service_stats_cache import StatsCache
from link_shortener.application.ports.cache.redirect_cache import RedirectCache
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.domain.repositories.link_repository import LinkRepository
from link_shortener.domain.policies.impl.hash_based import HashBasedShorteningPolicy
import pytest


@pytest.fixture
def shortening_policy():
    """Hash-based shortening policy with default code length 7."""
    return HashBasedShorteningPolicy(code_length=7)

@pytest.fixture
def mock_link_repository():
    """Mock for LinkRepository."""
    return Mock(spec=LinkRepository)

@pytest.fixture
def mock_link_cache():
    """Mock for LinkCache."""
    return Mock(spec=LinkCache)

@pytest.fixture
def mock_redirect_cache():
    """Mock for RedirectCache."""
    return Mock(spec=RedirectCache)

@pytest.fixture
def mock_stats_cache():
    """Mock for StatsCache."""
    return Mock(spec=StatsCache)

@pytest.fixture
def mock_logger():
    """Mock for Logger."""
    return Mock(spec=Logger)

@pytest.fixture
def base_url():
    """Base URL for short links."""
    return 'https://short.link'

from link_shortener.domain.entities.link import Link
from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.url_hash import UrlHash
import pytest

@pytest.fixture
def valid_url_str() -> str:
    """Return a valid URL string for testing."""
    return 'https://test.com/path/?q=test-link-1'

@pytest.fixture
def valid_original_url(valid_url_str) -> OriginalUrl:
    """Return an OriginalUrl value object from a valid URL string."""
    return OriginalUrl(valid_url_str)

@pytest.fixture
def valid_short_code_str() -> str:
    """Return a valid short code string for testing."""
    return 'abc123'

@pytest.fixture
def valid_short_code(valid_short_code_str) -> ShortCode:
    """Return a ShortCode value object from a valid string."""
    return ShortCode(valid_short_code_str)

@pytest.fixture
def valid_url_hash_str() -> str:
    """Return a valid URL hash string (64 hex characters)."""
    return 'a' * 64

@pytest.fixture
def valid_url_hash(valid_url_hash_str) -> UrlHash:
    """Return a UrlHash value object from a valid hex string."""
    return UrlHash(valid_url_hash_str)

@pytest.fixture
def sample_link(
    valid_url_hash, valid_short_code, valid_original_url
):
    """Provide a sample Link entity for testing."""

    return Link.create(
        url_hash=valid_url_hash,
        short_code=valid_short_code,
        original_url=valid_original_url
    )

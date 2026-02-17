from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.url_hash import UrlHash
import pytest

@pytest.fixture
def valid_url_str() -> str:
    return 'https://test.com/path/?q=test-link-1'

@pytest.fixture
def another_url_str() -> str:
    return 'https://test.com/path/?q=test-link-2'

@pytest.fixture
def valid_original_url(valid_url_str) -> OriginalUrl:
    return OriginalUrl(valid_url_str)

@pytest.fixture
def valid_short_code_str() -> str:
    return 'abc123'

@pytest.fixture
def valid_short_code(valid_short_code_str) -> ShortCode:
    return ShortCode(valid_short_code_str)

@pytest.fixture
def valid_url_hash_str() -> str:
    return 'a' * 64

@pytest.fixture
def valid_url_hash(valid_url_hash_str) -> UrlHash:
    return UrlHash(valid_url_hash_str)

@pytest.fixture
def another_url_hash_str() -> str:
    return 'b' * 64

from datetime import datetime
from typing import Any, Dict, List
from unittest.mock import Mock
import uuid
import pytest

from src.link_shortener.domain.entities.link import Link
from src.link_shortener.domain.interfaces.cache.abc_cache import ICacheClient
from src.link_shortener.domain.interfaces.database.abc_repository import ILinkRepository
from src.link_shortener.domain.interfaces.logger.abc_logger import ILogger
from src.link_shortener.domain.interfaces.utils.abc_code_extractor import IShortCodeExtractor
from src.link_shortener.domain.interfaces.utils.abc_code_generator import ICodeGenerator
from src.link_shortener.domain.interfaces.utils.abc_url_validator import IUrlValidator
from src.link_shortener.domain.services.cache.cache_manager import CacheManager

@pytest.fixture
def sample_link_data() -> Dict[str, Any]:
    """Фикстура для одной ссылки в Dict"""
    return {
        'id': str(uuid.uuid4()),
        'url_hash': 'hash123',
        'short_code': 'code123',
        'original_url': 'https://test.com/test',
        'created_at': datetime(2026, 2, 5, 0, 0),
        'clicks': 0,
        'last_accessed': None
    }

@pytest.fixture
def sample_link(sample_link_data) -> 'Link':
    """Фисктура для одной ссылки в Link"""
    return Link(**sample_link_data)

@pytest.fixture
def multiple_links() -> List[Link]:
    """Несколько тестовых ссылок Link"""
    links = []
    for i in range(5):
        link = Link.create(
            url_hash=f'hash_{i}',
            short_code=f'code_{i}',
            original_url=f'https://test{i}.com'
        )
        link.clicks = i * 10
        if i % 2 == 0:
            link.last_accessed = datetime(2026, 2, 7, i, 0, 0)
        links.append(link)
    return links

@pytest.fixture
def mock_logger() -> Mock:
    """Мок логгера"""
    logger = Mock(spec=ILogger)
    logger.debug = Mock()
    logger.info = Mock()
    logger.warning = Mock()
    logger.error = Mock()
    logger.exception = Mock()
    logger.bind = Mock(return_value=logger)
    logger.log = Mock()
    return logger

@pytest.fixture
def mock_cache_client() -> Mock:
    """Мок клиента кэша"""
    cache = Mock(spec=ICacheClient)
    cache.get = Mock(return_value=None)
    cache.set = Mock(return_value=True)
    cache.delete = Mock(return_value=True)
    cache.exists = Mock(return_value=False)
    cache.get_many = Mock(return_value={})
    cache.set_many = Mock(return_value=True)
    cache.clear = Mock(return_value=True)
    cache.get_cache_stats = Mock(return_value={})
    cache.close = Mock()
    return cache

@pytest.fixture
def mock_repository() -> Mock:
    """Мок репозитория"""
    repo = Mock(spec=ILinkRepository)
    repo.create = Mock()
    repo.create_or_get = Mock()
    repo.bulk_create = Mock(return_value=[])
    repo.get_by_short_code = Mock(return_value=None)
    repo.get_by_hash = Mock(return_value=None)
    repo.get_by_hashes = Mock(return_value=[])
    repo.increment_clicks = Mock(return_value=True)
    repo.update_clicks = Mock(return_value=True)
    repo.get_stats = Mock(return_value={})
    return repo

@pytest.fixture
def mock_url_validator() -> Mock:
    """Мок валидатора ссылок"""
    validator = Mock(spec=IUrlValidator)
    validator.is_valid_url = Mock(return_value=(True, 'test.com'))
    validator.normalize_url = Mock(return_value='test.com')
    validator.extract_domain = Mock(return_value='example')
    return validator

@pytest.fixture
def mock_code_generator() -> Mock:
    """Мок генератора кодов"""
    generator = Mock(spec=ICodeGenerator)
    generator.calculate_deduplication_hash = Mock(return_value='hash123')
    generator.generate_code = Mock(return_value="code123")
    generator.calclulate_entropy = Mock(return_value=(5.5, 100))
    return generator

@pytest.fixture
def mock_short_code_extractor() -> Mock:
    """Мок извлекателя короткого кода"""
    extractor = Mock(spec=IShortCodeExtractor)
    extractor.validate_short_url_format = Mock(return_value=(True, ""))
    extractor.extract_code_from_url = Mock(return_value="code123")
    extractor.get_base_url = Mock(return_value="https://short.com")
    return extractor

@pytest.fixture
def mock_cache_manager() -> Mock:
    """Мок Менеджера кэша"""
    cache_manager = Mock(spec=CacheManager)
    cache_manager.get_original_url = Mock(return_value=None)
    cache_manager.get_link_info = Mock(return_value=None)
    cache_manager.get_link_by_hash = Mock(return_value=None)
    cache_manager.get_link_by_hashes = Mock(return_value=[])
    cache_manager.cache_link = Mock(return_value=True)
    cache_manager.cache_links = Mock(return_value=True)
    cache_manager.cache_service_stats = Mock(return_value=True)
    cache_manager.invalidate_link = Mock(return_value=True)
    cache_manager.get_service_stats = Mock(return_value=None)
    cache_manager.get_cache_stats = Mock(return_value=None)
    return cache_manager



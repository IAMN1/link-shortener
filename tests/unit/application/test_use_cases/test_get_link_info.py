from datetime import datetime, timedelta
from link_shortener.application.dtos.responses import ExtendedLinkInfoResponse, ShortLinkResponse
from link_shortener.application.use_cases.get_link_info import GetExtendLinkInfoUseCase, GetLinkInfoUseCase
from link_shortener.domain.entities.link import Link
from link_shortener.domain.exceptions import LinkNotFoundError
import pytest


"""
Unit tests for get_link_info use cases.

Contains:
- TestGetLinkInfoUseCase: tests for GetLinkInfoUseCase (basic info)
- TestGetExtendLinkInfoUseCase: tests for GetExtendLinkInfoUseCase (extended info)
"""

@pytest.fixture
def link_info_use_case(
    mock_link_cache, mock_link_repository, mock_logger, base_url
) -> GetLinkInfoUseCase:
    """Fixture for GetLinkInfoUseCase."""
    
    return GetLinkInfoUseCase(
        repository=mock_link_repository,
        cache=mock_link_cache,
        base_url=base_url,
        logger=mock_logger,
    )

@pytest.fixture
def extended_link_info_use_case(
    mock_link_cache, mock_link_repository, mock_logger, base_url
) -> GetExtendLinkInfoUseCase:
    """Fixture for GetExtendLinkInfoUseCase."""
    
    return GetExtendLinkInfoUseCase(
        repository=mock_link_repository,
        cache=mock_link_cache,
        base_url=base_url,
        logger=mock_logger,
    )

@pytest.fixture
def old_link(valid_url_hash, valid_short_code, valid_original_url):
    """Fixture for a link created 10 days ago with 50 clicks."""
    
    link = Link.create(
        url_hash=valid_url_hash,
        short_code=valid_short_code,
        original_url=valid_original_url
    )
    # Подмена created_at
    link.created_at = datetime.now() - timedelta(days=10)
    link.clicks = 50
    link.last_accessed = datetime.now() - timedelta(days=2)

    return link

@pytest.fixture
def sample_link(valid_url_hash, valid_short_code, valid_original_url):
    """Fixture for a generic link."""
    
    return Link.create(
        url_hash=valid_url_hash,
        short_code=valid_short_code,
        original_url=valid_original_url
    )


# ------------------------------------------------------------------
# TestGetLinkInfoUseCase
# ------------------------------------------------------------------
class TestGetLinkInfoUseCase:
    """
    Tests for GetLinkInfoUseCase.
    Scenarios:
      - Link in cache – return from cache, no DB call.
      - Link not in cache but in DB – get from DB and cache.
      - Link not found – raise LinkNotFoundError.
      - Invalid short code – raise ValueError.
    """

    def test_happy_path_from_cache(
        self, link_info_use_case, sample_link, mock_link_repository, mock_link_cache
    ):
        """Should return link from cache when present."""

        short_code_str = sample_link.short_code.value
        mock_link_cache.get_by_code.return_value = sample_link

        # Act
        response = link_info_use_case.execute(short_code_str)

        # Assert
        assert isinstance(response, ShortLinkResponse)
        assert response.short_code == short_code_str
        assert response.from_cache is True
        mock_link_repository.find_by_code.assert_not_called()
        mock_link_cache.save.assert_not_called()
    
    def test_happy_path_from_db(
        self, link_info_use_case, sample_link, mock_link_cache, mock_link_repository
    ):
        """Should return link from DB when not in cache, and cache it."""
        
        # Arrange
        short_code_str = sample_link.short_code.value
        mock_link_cache.get_by_code.return_value = None
        mock_link_repository.find_by_code.return_value = sample_link

        # Act
        response = link_info_use_case.execute(short_code_str)

        # Assert
        assert response.short_code == short_code_str
        assert response.from_cache is False
        mock_link_repository.find_by_code.assert_called_once()
        mock_link_cache.save.assert_called_once_with(sample_link)
    
    def test_link_not_found_riases_exception(
        self, link_info_use_case, mock_link_cache, mock_link_repository
    ):
        """Should raise LinkNotFoundError when link not in cache or DB."""

        short_code_str = 'abc123'
        mock_link_cache.get_by_code.return_value = None
        mock_link_repository.find_by_code.return_value = None

        with pytest.raises(LinkNotFoundError):
            link_info_use_case.execute(short_code_str)
    
    def test_invalid_short_code_raises_value_error(
        self, link_info_use_case, mock_link_cache, mock_link_repository
    ):
        """Should raise ValueError for invalid short code format."""

        invalid_code = 'code' # < min_value for code (def = 6)

        with pytest.raises(ValueError, match='Invalid short code'):
            link_info_use_case.execute(invalid_code)
        
        # никаких обращений к кэшу или бд
        mock_link_cache.get_by_code.assert_not_called()
        mock_link_repository.find_by_code.assert_not_called()
    
    def get_link_info_repository_exception(
        self, link_info_use_case, mock_link_cache, mock_link_repository
    ):
        """Should log and re-raise exception when repository fails."""

        # Arrange
        short_code_str = "abc123"
        mock_link_cache.get_by_code.return_value = None
        mock_link_repository.find_by_code.side_effect = Exception("DB error")

        # Act & Assert
        with pytest.raises(Exception, match="DB error"):
            link_info_use_case.execute(short_code_str)
        link_info_use_case.logger.error.assert_called_once()


# ------------------------------------------------------------------
# TestGetExtendLinkInfoUseCase
# ------------------------------------------------------------------
class TestGetExtendLinkInfoUseCase:
    """Tests for GetExtendLinkInfoUseCase."""

    def test_get_info_from_cache(
        self, extended_link_info_use_case, mock_link_cache, mock_link_repository, old_link
    ):
        """Should return extended info from cache when present."""

        short_code_str = old_link.short_code.value
        mock_link_cache.get_by_code.return_value = old_link

        response = extended_link_info_use_case.execute(short_code_str)

        assert isinstance(response, ExtendedLinkInfoResponse)
        assert response.short_code == short_code_str
        assert response.clicks == 50
        assert response.age_days == 10
        assert response.clicks_per_day == 5.0  # 50 / 10
        assert response.last_access_days_ago == 2
        assert response.is_popular is False  # threshold 100
        assert response.is_recent is False   # days=7
        mock_link_repository.find_by_code.assert_not_called()
    
    def test_from_db(
        self, extended_link_info_use_case, mock_link_cache, mock_link_repository, old_link
    ):
        """Should return extended info from DB when not in cache, and cache it."""
        short_code_str = old_link.short_code.value
        mock_link_cache.get_by_code.return_value = None
        mock_link_repository.find_by_code.return_value = old_link

        # Act
        response = extended_link_info_use_case.execute(short_code_str)

        assert response.short_code == short_code_str
        assert response.clicks == 50
        assert response.age_days == 10
        assert response.clicks_per_day == 5.0
        mock_link_cache.save.assert_called_once_with(old_link)
    
    def test_link_not_found(
        self, extended_link_info_use_case, mock_link_cache, mock_link_repository, old_link
    ):
        """Should raise LinkNotFoundError when link does not exist."""
        short_code_str = 'test123'
        mock_link_cache.get_by_code.return_value = None
        mock_link_repository.find_by_code.return_value = None

        with pytest.raises(LinkNotFoundError):
            extended_link_info_use_case.execute(short_code_str)
    
    def test_invalid_code(
        self, extended_link_info_use_case, old_link, mock_link_cache, mock_link_repository
    ):
        """Should raise ValueError for invalid short code format."""
        invalid_code = 'code' # не входит в диапазон (от 6 до 10)
        
        with pytest.raises(ValueError, match='Invalid short code'):
            extended_link_info_use_case.execute(invalid_code)
    
    def test_extended_info_last_accessed_none(
        self, extended_link_info_use_case, mock_link_cache, mock_link_repository,
        valid_url_hash, valid_short_code, valid_original_url
    ):
        """
        Should return ExtendedLinkInfoResponse
        with last_access_days_ago = None when link never accessed.
        """
        
        link = Link.create(
            url_hash=valid_url_hash,
            short_code=valid_short_code,
            original_url=valid_original_url
        )
        link.clicks = 0
        link.last_accessed = None
        link.created_at = datetime.now() - timedelta(days=5)

        mock_link_cache.get_by_code.return_value = None
        mock_link_repository.find_by_code.return_value = link

        response = extended_link_info_use_case.execute(valid_short_code.value)

        assert response.last_access_days_ago is None
        assert response.clicks_per_day == 0.0

    def test_get_extended_link_info_repository_exception(
        self, extended_link_info_use_case, mock_link_cache, mock_link_repository
    ):
        """Should log and re-raise exception when repository fails."""

        # Arrange
        short_code_str = "abc123"
        mock_link_cache.get_by_code.return_value = None
        mock_link_repository.find_by_code.side_effect = Exception("DB error")

        # Act & Assert
        with pytest.raises(Exception, match="DB error"):
            extended_link_info_use_case.execute(short_code_str)
        extended_link_info_use_case.logger.error.assert_called_once()

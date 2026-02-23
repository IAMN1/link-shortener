from unittest.mock import Mock
from link_shortener.application.use_cases.redirect_link import RedirectLinkUseCase
from link_shortener.domain.entities.link import Link
from link_shortener.domain.exceptions import LinkNotFoundError
import pytest


@pytest.fixture
def use_case(
    mock_link_repository, mock_link_cache, mock_redirect_cache, mock_logger, mock_audit_logger
) -> RedirectLinkUseCase:
    """Provide a RedirectLinkUseCase instance with mocked dependencies."""

    return RedirectLinkUseCase(
        repository=mock_link_repository,
        link_cache=mock_link_cache,
        redirect_cache=mock_redirect_cache,
        logger=mock_logger,
        audit_logger=mock_audit_logger
    )

@pytest.fixture
def sample_link(
    valid_original_url, valid_short_code, valid_url_hash
) -> Link:
    """Provide a sample Link for testing."""
    
    link = Link.create(
        url_hash=valid_url_hash,
        short_code=valid_short_code,
        original_url=valid_original_url
    )
    link.clicks = 10

    return link


# ------------------------------------------------------------------
# TestRedirectLinkUseCase
# ------------------------------------------------------------------
class TestRedirectLinkUseCase:
    """Tests for RedirectLinkUseCase."""

    def test_redirect_from_L1_cache(
        self, use_case, mock_link_cache, mock_redirect_cache, mock_link_repository, sample_link
    ):
        """
        Should return URL from L1 (redirect) cache
        and increment clicks asynchronously.
        """
        
        short_code = sample_link.short_code.value
        expected_url = sample_link.original_url.value
        mock_redirect_cache.get_original_url.return_value = expected_url
        # мок инкремента для проверки его вызова
        use_case._audit_and_update_async = Mock()

        # Act
        result = use_case.execute(short_code)

        assert result == expected_url
        mock_redirect_cache.get_original_url.assert_called_once_with(sample_link.short_code)
        mock_link_cache.get_by_code.assert_not_called()
        mock_link_repository.find_by_code.assert_not_called()
        use_case._audit_and_update_async.assert_called_once_with(
            sample_link.short_code, None, None
        )

    def test_redirect_from_L2_cache(
        self, use_case, mock_link_cache, mock_redirect_cache, sample_link
    ):
        """Should return URL from L2 (link) cache and save to L1 cache."""

        short_code = sample_link.short_code.value
        expected_url = sample_link.original_url.value
        mock_redirect_cache.get_original_url.return_value = None
        mock_link_cache.get_by_code.return_value = sample_link
        use_case._audit_and_update_async = Mock()

        # Act
        result = use_case.execute(short_code)

        assert result == expected_url
        mock_redirect_cache.save_original_url.assert_called_once_with(
            sample_link.short_code, expected_url
        )
        use_case._audit_and_update_async.assert_called_once_with(
            sample_link.short_code, None, None
        )

    def test_redirect_from_repository(
        self, use_case, mock_redirect_cache, mock_link_cache, mock_link_repository, sample_link
    ):
        """Should return URL from repository when not found in cache, and cache it."""

        short_code = sample_link.short_code.value
        expected_url = sample_link.original_url.value
        mock_redirect_cache.get_original_url.return_value = None
        mock_link_cache.get_by_code.return_value = None
        mock_link_repository.find_by_code.return_value = sample_link
        use_case._audit_and_update_async = Mock()

        # Act
        result = use_case.execute(short_code)

        assert result == expected_url
        mock_link_repository.find_by_code.assert_called_once_with(sample_link.short_code)
        mock_link_repository.increment_clicks.assert_called_once_with(sample_link.short_code)
        mock_link_cache.save.assert_called_once_with(sample_link)
        # проверка, что происходит вызыв сохранения на всех уровнях кэша
        mock_redirect_cache.save_original_url.assert_not_called()
        use_case._audit_and_update_async.assert_not_called()

    def test_link_not_found(
        self, use_case, mock_redirect_cache, mock_link_cache, mock_link_repository
    ):
        """Should raise LinkNotFoundError when link not found in cache or DB."""
        short_code_str = 'abc123'
        mock_redirect_cache.get_original_url.return_value = None
        mock_link_cache.get_by_code.return_value = None
        mock_link_repository.find_by_code.return_value = None

        with pytest.raises(LinkNotFoundError):
            use_case.execute(short_code_str)

    def test_invalid_code(
        self, use_case, mock_redirect_cache, mock_link_cache, mock_link_repository
    ):
        """Should raise ValueError for invalid short code format."""
        
        invalid_code = 'bad'

        with pytest.raises(ValueError, match='Invalid short code'):
            use_case.execute(invalid_code)

        mock_redirect_cache.get_original_url.assert_not_called()

    def test_audit_and_update_async_success(
        self, use_case, mock_link_repository, mock_link_cache, sample_link
    ):
        """Should successfully increment clicks in DB and update cache."""

        mock_link_cache.get_by_code.return_value = None
        mock_link_repository.find_by_code.return_value = sample_link
        mock_link_repository.increment_clicks.return_value = None

        # Act
        use_case._audit_and_update_async(
            sample_link.short_code, "127.0.0.1", "Mozilla"
        )
        
        # Assert
        mock_link_cache.get_by_code.assert_called_once_with(sample_link.short_code)
        mock_link_repository.find_by_code.assert_called_once_with(sample_link.short_code)
        use_case.audit_logger.log_url_accessed.assert_called_once()
        mock_link_repository.increment_clicks.assert_called_once_with(sample_link.short_code)
        mock_link_cache.save.assert_called_once_with(sample_link)
        assert sample_link.clicks == 11 # было 10 стало 11

    def test_audit_and_update_async_link_not_found(
        self, use_case, mock_link_repository, mock_link_cache, sample_link
    ):
        """
        Should log error but not raise when link not found
        during background increment.
        """

        mock_link_cache.get_by_code.return_value = None
        mock_link_repository.find_by_code.return_value = None

        # Act
        use_case._audit_and_update_async(sample_link.short_code, None, None)

        # Assert
        mock_link_cache.get_by_code.assert_called_once()
        mock_link_repository.find_by_code.assert_called_once()
        use_case.audit_logger.log_url_accessed.assert_not_called()
        mock_link_repository.increment_clicks.assert_not_called()
        mock_link_cache.save.assert_not_called()
        use_case.logger.error.assert_called_once()

    def test_audit_and_update_async_exception_handling(
        self, use_case, mock_link_repository, mock_link_cache, sample_link
    ):
        """
        Should log error but not raise exception when background click increment fails.
        """
        mock_link_cache.get_by_code.return_value = None
        mock_link_repository.find_by_code.return_value = sample_link
        mock_link_repository.increment_clicks.side_effect = Exception("DB error")

        use_case._audit_and_update_async(sample_link.short_code, None, None)

        use_case.logger.error.assert_called_once()
        mock_link_cache.save.assert_not_called()
    

    def test_redirect_repository_exception(
        self, use_case, mock_redirect_cache, mock_link_cache, mock_link_repository
    ):
        """Should log and re-raise exception when repository fails."""
        short_code_str = "abc123"
        mock_redirect_cache.get_original_url.return_value = None
        mock_link_cache.get_by_code.return_value = None
        mock_link_repository.find_by_code.side_effect = Exception("DB error")

        with pytest.raises(RuntimeError, match="Failed to redirect: DB error"):
            use_case.execute(short_code_str)
        use_case.logger.exception.assert_called_once()

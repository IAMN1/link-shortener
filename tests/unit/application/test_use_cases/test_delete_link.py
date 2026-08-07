from unittest.mock import Mock, MagicMock

from link_shortener.application.context import RequestContext
from link_shortener.application.use_cases.links.delete_link import DeleteLinkUseCase
from link_shortener.domain import Link, ShortCode, UrlHash, OriginalUrl
import pytest


@pytest.fixture
def mock_uow_factory():
    uow = Mock()
    factory = Mock(return_value=MagicMock())
    factory.return_value.__enter__ = Mock(return_value=uow)
    factory.return_value.__exit__ = Mock(return_value=False)
    return factory, uow


@pytest.fixture
def mock_cache():
    return Mock()


@pytest.fixture
def mock_redirect_cache():
    return Mock()


@pytest.fixture
def mock_logger():
    logger = Mock()
    logger.bind.return_value = Mock()
    return logger


@pytest.fixture
def mock_audit_logger():
    al = Mock()
    al.bind.return_value = Mock()
    return al


@pytest.fixture
def context():
    return RequestContext(
        request_id="req-1",
        remote_addr="127.0.0.1",
        user_agent="Mozilla/5.0",
        request_path="/api/v1/links/abc123",
        request_method="DELETE",
    )


@pytest.fixture
def sample_link():
    return Link.create(
        url_hash=UrlHash("a" * 64),
        short_code=ShortCode("abc123"),
        original_url=OriginalUrl("https://example.com"),
    )


@pytest.fixture
def use_case(mock_uow_factory, mock_cache, mock_redirect_cache, mock_logger, mock_audit_logger):
    factory, _ = mock_uow_factory
    return DeleteLinkUseCase(
        uow_factory=factory,
        cache=mock_cache,
        stats_cache=mock_cache,
        redirect_cache=mock_redirect_cache,
        logger=mock_logger,
        audit_logger=mock_audit_logger,
        authorization_service=Mock(),
    )


class TestDeleteLinkUseCase:
    """Tests for the DeleteLinkUseCase."""

    def test_delete_existing_link(
        self, use_case, mock_uow_factory, mock_cache, mock_redirect_cache, sample_link, context
    ):
        factory, uow = mock_uow_factory
        uow.links.find_by_code.return_value = sample_link
        uow.links.delete.return_value = True

        result = use_case.execute("abc123", context, enforce_ownership=False)

        assert result is True
        uow.links.delete.assert_called_once()
        uow.commit.assert_called_once()
        # The entity, not the code: only it names the deduplication key.
        mock_cache.delete.assert_called_once_with(sample_link)
        mock_redirect_cache.delete_redirect.assert_called_once()

    def test_delete_nonexistent_link(
        self, use_case, mock_uow_factory, mock_cache, mock_redirect_cache, context
    ):
        factory, uow = mock_uow_factory
        uow.links.find_by_code.return_value = None

        result = use_case.execute("abc123", context, enforce_ownership=False)

        assert result is False
        uow.links.delete.assert_not_called()
        # Nothing is deleted from the table, and the entity-keyed
        # invalidation cannot run without an entity.
        mock_cache.delete.assert_not_called()

    def test_a_cache_entry_that_outlived_its_row_is_still_cleared(
        self, use_case, mock_uow_factory, mock_cache, mock_redirect_cache, context
    ):
        """
        The answer stays 404, but the code-keyed entries go.

        An entry surviving its row is the state a second DELETE is issued to
        clear: every API surface calls the link deleted while the redirect
        keeps serving it for the rest of CACHE_LINK_TTL. Returning early
        left no command in the service able to touch it.
        """
        factory, uow = mock_uow_factory
        uow.links.find_by_code.return_value = None

        use_case.execute("abc123", context, enforce_ownership=False)

        mock_cache.delete_by_code.assert_called_once()
        mock_redirect_cache.delete_redirect.assert_called_once()

    def test_cache_invalidated_after_delete(
        self, use_case, mock_uow_factory, mock_cache, mock_redirect_cache, sample_link, context
    ):
        factory, uow = mock_uow_factory
        uow.links.find_by_code.return_value = sample_link
        uow.links.delete.return_value = True

        use_case.execute("abc123", context, enforce_ownership=False)

        mock_cache.delete.assert_called_once()
        mock_redirect_cache.delete_redirect.assert_called_once()

    def test_invalid_short_code_returns_false(
        self, use_case, mock_uow_factory, mock_cache, mock_redirect_cache, context
    ):
        result = use_case.execute("", context, enforce_ownership=False)

        assert result is False
        mock_cache.delete.assert_not_called()
        mock_redirect_cache.delete_redirect.assert_not_called()

    def test_delete_fails_returns_false(
        self, use_case, mock_uow_factory, mock_cache, mock_redirect_cache, sample_link, context
    ):
        factory, uow = mock_uow_factory
        uow.links.find_by_code.return_value = sample_link
        uow.links.delete.return_value = False

        result = use_case.execute("abc123", context, enforce_ownership=False)

        assert result is False
        uow.commit.assert_not_called()
        mock_cache.delete.assert_not_called()
        mock_redirect_cache.delete_redirect.assert_not_called()

from unittest.mock import Mock
from link_shortener.application.dtos.link import ShortLinkResponse
from link_shortener.application.dtos.batch import BatchCreateResponse
from link_shortener.application.dtos.stats import ServiceStatsResponse
from link_shortener.application.services.link_service import LinkService
import pytest


@pytest.fixture
def mock_create_use_case():
    return Mock()

@pytest.fixture
def mock_get_info_use_case():
    return Mock()

@pytest.fixture
def mock_get_extended_info_use_case():
    return Mock()

@pytest.fixture
def mock_redirect_use_case():
    return Mock()

@pytest.fixture
def mock_batch_create_use_case():
    return Mock()

@pytest.fixture
def mock_get_stats_use_case():
    return Mock()

@pytest.fixture
def mock_get_user_links_use_case():
    return Mock()

@pytest.fixture
def mock_delete_link_use_case():
    return Mock()

@pytest.fixture
def link_service(
    mock_create_use_case,
    mock_get_info_use_case,
    mock_get_extended_info_use_case,
    mock_redirect_use_case,
    mock_batch_create_use_case,
    mock_get_stats_use_case,
    mock_get_user_links_use_case,
    mock_delete_link_use_case,
):
    return LinkService(
        create_short_link_use_case=mock_create_use_case,
        get_link_info_use_case=mock_get_info_use_case,
        get_extended_link_info_use_case=mock_get_extended_info_use_case,
        redirect_link_use_case=mock_redirect_use_case,
        batch_create_links_use_case=mock_batch_create_use_case,
        get_service_stats_use_case=mock_get_stats_use_case,
        get_user_links_use_case=mock_get_user_links_use_case,
        delete_link_use_case=mock_delete_link_use_case,
    )


class TestLinkService:
    """Tests for the LinkService facade (delegation to use cases)."""

    def test_create_short_link_delegates(self, link_service, mock_create_use_case):
        """Should delegate to CreateShortLinkUseCase.execute()."""
        from link_shortener.application.context import RequestContext

        context = RequestContext(request_id="test-1")
        expected_response = Mock(spec=ShortLinkResponse)
        mock_create_use_case.execute.return_value = expected_response

        result = link_service.create_short_link("https://test.com", context)

        assert result == expected_response
        mock_create_use_case.execute.assert_called_once_with(
            "https://test.com", context, ttl_seconds=0, custom_code=None
        )

    def test_create_short_link_passes_a_chosen_code_through(
        self, link_service, mock_create_use_case
    ):
        """A code the caller picked is theirs to keep, not a hint."""
        from link_shortener.application.context import RequestContext

        context = RequestContext(request_id="test-1")

        link_service.create_short_link(
            "https://test.com", context, custom_code="my-code"
        )

        mock_create_use_case.execute.assert_called_once_with(
            "https://test.com", context, ttl_seconds=0, custom_code="my-code"
        )

    def test_get_link_info_delegates(self, link_service, mock_get_info_use_case):
        """Should delegate to GetLinkInfoUseCase.execute()."""
        from link_shortener.application.context import RequestContext

        context = RequestContext(request_id="test-1")
        expected_response = Mock(spec=ShortLinkResponse)
        mock_get_info_use_case.execute.return_value = expected_response

        result = link_service.get_link_info("abc123", context)

        assert result == expected_response
        mock_get_info_use_case.execute.assert_called_once_with("abc123", context)

    def test_delete_link_delegates(self, link_service, mock_delete_link_use_case):
        """Should delegate to DeleteLinkUseCase.execute()."""
        from link_shortener.application.context import RequestContext

        context = RequestContext(request_id="test-1")
        mock_delete_link_use_case.execute.return_value = True

        result = link_service.delete_link(
            "abc123", context, enforce_ownership=True
        )

        assert result is True
        # Passed through, not re-decided: a facade that could soften this
        # would be a second place to get authorization wrong.
        mock_delete_link_use_case.execute.assert_called_once_with(
            "abc123", context, enforce_ownership=True, authorized_link_id=None
        )

    def test_delete_link_passes_the_deletion_token_through(
        self, link_service, mock_delete_link_use_case
    ):
        """
        The token is what speaks for the creator of a guest link, which has
        no owner for ownership to match against. A facade that dropped it
        would leave such a link undeletable by the person who made it.
        """
        from link_shortener.application.context import RequestContext

        context = RequestContext(request_id="test-1")

        link_service.delete_link(
            "abc123", context, enforce_ownership=True,
            authorized_link_id="link-42",
        )

        mock_delete_link_use_case.execute.assert_called_once_with(
            "abc123", context, enforce_ownership=True,
            authorized_link_id="link-42",
        )

    def test_get_user_links_delegates(self, link_service, mock_get_user_links_use_case):
        """Should delegate to GetUserLinksUseCase.execute()."""
        from link_shortener.application.context import RequestContext

        context = RequestContext(request_id="test-1")
        mock_get_user_links_use_case.execute.return_value = []

        result = link_service.get_user_links("user-123", context)

        assert result == []
        mock_get_user_links_use_case.execute.assert_called_once_with(
            "user-123", context, offset=0, limit=50
        )

from unittest.mock import Mock
from link_shortener.application.dtos.responses import BatchCreateResponse, ServiceStatsResponse, ShortLinkResponse
from link_shortener.application.services.link_service import LinkService
import pytest


@pytest.fixture
def mock_create_use_case():
    return Mock()

@pytest.fixture
def mock_get_info_use_case():
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
def link_service(
    mock_create_use_case,
    mock_get_info_use_case,
    mock_redirect_use_case,
    mock_batch_create_use_case,
    mock_get_stats_use_case
):
    return LinkService(
        create_short_link_use_case=mock_create_use_case,
        get_link_info_use_case=mock_get_info_use_case,
        redirect_link_use_case=mock_redirect_use_case,
        batch_create_links_use_case=mock_batch_create_use_case,
        get_service_stats_use_case=mock_get_stats_use_case
    )


# ------------------------------------------------------------------
# TestLinkService
# ------------------------------------------------------------------
class TestLinkService:
    """Tests for the LinkService facade (delegation to use cases)."""

    def test_create_short_link_delegates(self, link_service, mock_create_use_case):
        """Should delegate to CreateShortLinkUseCase.execute()."""

        url = 'https://test.com'
        user_ip = "127.0.0.1"
        user_agent = "Mozilla"
        expected_response = Mock(spec=ShortLinkResponse)
        mock_create_use_case.execute.return_value = expected_response

        result = link_service.create_short_link(url, user_ip, user_agent)

        assert result == expected_response
        mock_create_use_case.execute.assert_called_once_with(url, user_ip, user_agent)

    def test_get_link_info_delegates(self, link_service, mock_get_info_use_case):
        """Should delegate to GetLinkInfoUseCase.execute()."""
        
        short_code = 'abc123'
        expected_response = Mock(spec=ShortLinkResponse)
        mock_get_info_use_case.execute.return_value = expected_response

        result = link_service.get_link_info(short_code)

        assert result == expected_response
        mock_get_info_use_case.execute.assert_called_once_with(short_code)

    def test_redirect_delegates(self, link_service, mock_redirect_use_case):
        """Should delegate to RedirectLinkUseCase.execute()."""
        
        short_code = 'abc123'
        expected_url = 'https://original.com'
        user_ip = "127.0.0.1"
        user_agent = "Mozilla"
        mock_redirect_use_case.execute.return_value = expected_url

        result = link_service.redirect(short_code, user_ip, user_agent)

        assert result == expected_url
        mock_redirect_use_case.execute.assert_called_once_with(
            short_code, user_ip, user_agent
        )

    def test_batch_create_delegates(self, link_service, mock_batch_create_use_case):
        """Should delegate to BatchCreateLinksUseCase.execute()."""
        
        urls = ['https://a.com', 'https://b.com']
        user_ip = "127.0.0.1"
        user_agent = "Mozilla"
        expected_response = Mock(spec=BatchCreateResponse)
        mock_batch_create_use_case.execute.return_value = expected_response

        result = link_service.batch_create_short_links(urls, user_ip, user_agent)

        assert result == expected_response
        mock_batch_create_use_case.execute.assert_called_once_with(
            urls, user_ip, user_agent
        )

    def test_get_service_stats_delegates(self, link_service, mock_get_stats_use_case):
        """Should delegate to GetServiceStatsUseCase.execute()."""
        
        expected_response = Mock(spec=ServiceStatsResponse)
        mock_get_stats_use_case.execute.return_value = expected_response

        result = link_service.get_service_stats()

        assert result == expected_response
        mock_get_stats_use_case.execute.assert_called_once()

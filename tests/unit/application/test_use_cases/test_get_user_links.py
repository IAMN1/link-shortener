from unittest.mock import Mock, MagicMock

from link_shortener.application.context import RequestContext
from link_shortener.application.use_cases.links.get_user_links import GetUserLinksUseCase
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
def context():
    return RequestContext(
        request_id="req-1",
        remote_addr="127.0.0.1",
        user_agent="Mozilla/5.0",
        request_path="/api/v1/links/mine",
        request_method="GET",
    )


@pytest.fixture
def use_case(mock_uow_factory):
    factory, _ = mock_uow_factory
    return GetUserLinksUseCase(
        uow_factory=factory,
        base_url="https://short.link",
    )


class TestGetUserLinksUseCase:
    """Tests for the GetUserLinksUseCase."""

    def test_returns_empty_list_when_no_links(
        self, use_case, mock_uow_factory, context
    ):
        factory, uow = mock_uow_factory
        uow.links.find_by_owner.return_value = []

        result = use_case.execute("user-123", context)

        assert result == []
        uow.links.find_by_owner.assert_called_once_with("user-123", offset=0, limit=50)

    def test_returns_links_for_user(
        self, use_case, mock_uow_factory, context
    ):
        factory, uow = mock_uow_factory
        link = Link.create(
            url_hash=UrlHash("a" * 64),
            short_code=ShortCode("abc123"),
            original_url=OriginalUrl("https://example.com"),
        )
        uow.links.find_by_owner.return_value = [link]

        result = use_case.execute("user-123", context)

        assert len(result) == 1
        assert result[0].short_code == "abc123"

    def test_pagination_params_passed(
        self, use_case, mock_uow_factory, context
    ):
        factory, uow = mock_uow_factory
        uow.links.find_by_owner.return_value = []

        use_case.execute("user-123", context, offset=10, limit=25)

        uow.links.find_by_owner.assert_called_once_with("user-123", offset=10, limit=25)

    def test_limit_capped_at_200(
        self, use_case, mock_uow_factory, context
    ):
        factory, uow = mock_uow_factory
        uow.links.find_by_owner.return_value = []

        use_case.execute("user-123", context, limit=500)

        uow.links.find_by_owner.assert_called_once_with("user-123", offset=0, limit=200)

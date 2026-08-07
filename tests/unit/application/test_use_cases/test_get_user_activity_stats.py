from unittest.mock import Mock, MagicMock

from link_shortener.application.context import RequestContext
from link_shortener.application.use_cases.stats.get_user_activity_stats import GetUserActivityStatsUseCase
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
        request_path="/api/v1/stats/mine",
        request_method="GET",
    )


@pytest.fixture
def use_case(mock_uow_factory):
    factory, _ = mock_uow_factory
    return GetUserActivityStatsUseCase(
        uow_factory=factory,
        base_url="https://short.link",
    )


class TestGetUserActivityStatsUseCase:
    """Tests for the GetUserActivityStatsUseCase."""

    def test_returns_zero_stats_when_no_links(
        self, use_case, mock_uow_factory, context
    ):
        factory, uow = mock_uow_factory
        uow.links.get_user_stats.return_value = {
            "total_links": 0,
            "total_clicks": 0,
            "recent_links": [],
        }

        result = use_case.execute("user-123", context)

        assert result.total_links == 0
        assert result.total_clicks == 0
        assert result.avg_clicks_per_link == 0.0
        assert result.recent_links == []

    def test_returns_correct_stats(
        self, use_case, mock_uow_factory, context
    ):
        factory, uow = mock_uow_factory
        link1 = Link.create(
            url_hash=UrlHash("a" * 64),
            short_code=ShortCode("abc123"),
            original_url=OriginalUrl("https://example.com"),
        )
        link1.clicks = 10
        link2 = Link.create(
            url_hash=UrlHash("b" * 64),
            short_code=ShortCode("def456"),
            original_url=OriginalUrl("https://example.org"),
        )
        link2.clicks = 20

        uow.links.get_user_stats.return_value = {
            "total_links": 2,
            "total_clicks": 30,
            "recent_links": [link1, link2],
        }

        result = use_case.execute("user-123", context)

        assert result.total_links == 2
        assert result.total_clicks == 30
        assert result.avg_clicks_per_link == 15.0
        assert len(result.recent_links) == 2

    def test_avg_clicks_zero_when_no_links(
        self, use_case, mock_uow_factory, context
    ):
        factory, uow = mock_uow_factory
        uow.links.get_user_stats.return_value = {
            "total_links": 0,
            "total_clicks": 0,
            "recent_links": [],
        }

        result = use_case.execute("user-123", context)

        assert result.avg_clicks_per_link == 0.0

    def test_stats_with_single_link(
        self, use_case, mock_uow_factory, context
    ):
        factory, uow = mock_uow_factory
        link = Link.create(
            url_hash=UrlHash("a" * 64),
            short_code=ShortCode("abc123"),
            original_url=OriginalUrl("https://example.com"),
        )
        link.clicks = 5

        uow.links.get_user_stats.return_value = {
            "total_links": 1,
            "total_clicks": 5,
            "recent_links": [link],
        }

        result = use_case.execute("user-123", context)

        assert result.total_links == 1
        assert result.total_clicks == 5
        assert result.avg_clicks_per_link == 5.0

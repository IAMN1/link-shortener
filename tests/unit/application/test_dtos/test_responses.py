from link_shortener.application.dtos.link import ShortLinkResponse, ExtendedLinkInfoResponse
from link_shortener.application.dtos.batch import BatchCreateResponse, BatchItemResponse
from link_shortener.application.dtos.stats import ServiceStatsResponse, StatsItemResponse
from link_shortener.domain.value_objects.url_hash import UrlHash
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.domain.entities.link import Link
from datetime import datetime, timedelta, timezone
import pytest


# ------------------------------------------------------------------
# TestShortLinkResponse
# ------------------------------------------------------------------
class TestShortLinkResponse:
    """Tests for ShortLinkResponse DTO."""

    def test_from_link_creates_correct_fields(self):
        """Should create ShortLinkResponse with correct fields from Link entity."""
        
        url_hash = UrlHash('a'*64)
        short_code = ShortCode('abc123')
        original_url = OriginalUrl('https://example.com')
        link = Link.create(
            url_hash=url_hash,
            short_code=short_code,
            original_url=original_url
        )
        # set some values for testing
        link.clicks = 42
        link.last_accessed = datetime.now() - timedelta(days=1)

        base_url = 'https://short.link'
        response = ShortLinkResponse.from_link(
            link=link,
            base_url=base_url,
            is_new=True,
            from_cache=False
        )

        assert response.short_code == 'abc123'
        assert response.short_url == 'https://short.link/abc123'
        assert response.original_url == 'https://example.com'
        assert response.clicks == 42
        assert response.created_at == link.created_at
        assert response.last_accessed == link.last_accessed
        assert response.is_new is True
        assert response.from_cache is False
    
    def test_to_dict(self):
        """Should convert ShortLinkResponse to dictionary with ISO formatted dates."""

        url_hash = UrlHash('a'*64)
        short_code = ShortCode('abc123')
        original_url = OriginalUrl('https://example.com')
        link = Link.create(
            url_hash=url_hash,
            short_code=short_code,
            original_url=original_url
        )
        link.clicks = 42
        link.last_accessed = datetime.now() - timedelta(days=1)

        base_url = 'https://short.link'
        response = ShortLinkResponse.from_link(link, base_url)
        data = response.to_dict()

        assert data['short_code'] == 'abc123'
        assert data['short_url'] == 'https://short.link/abc123'
        assert data['original_url'] == 'https://example.com'
        assert data['clicks'] == 42
        assert 'created_at' in data
        assert 'last_accessed' in data
        assert data['is_new'] is False
        assert data['from_cache'] is False


# ------------------------------------------------------------------
# BatchItemResponse
# ------------------------------------------------------------------
class TestBatchItemResponse:
    """Tests for BatchItemResponse DTO."""

    def test_success_factory(self, base_url):
        """Should create success BatchItemResponse with given fields."""

        url = 'https://example.com'
        short_code = 'abc123'
        original_url = 'https://example.com'
        response = BatchItemResponse.success_(
            url=url,
            short_code=short_code,
            original_url=original_url,
            base_url=base_url,
            clicks=10,
            is_new=True,
            from_cache=False,
            duplicate_of=None
        )
        assert response.success is True
        assert response.url == url
        assert response.short_code == short_code
        assert response.original_url == original_url
        assert response.short_url == f"{base_url.rstrip("/")}/{short_code}"
        assert response.clicks == 10
        assert response.is_new is True
        assert response.from_cache is False
        assert response.error is None
        assert response.duplicate_of is None

    def test_error_factory(self):
        """Should create error BatchItemResponse with error message."""
        
        url = 'https://example.com'
        error = 'Invalid URL'

        response = BatchItemResponse.error_(url, error)

        assert response.success is False
        assert response.url == url
        assert response.error == error
        assert response.short_url is None


# ------------------------------------------------------------------
# BatchCreateResponse
# ------------------------------------------------------------------
class TestBatchCreateResponse:
    """Tests for BatchCreateResponse DTO."""

    def test_from_results_calculates_counts(self, base_url):
        """Should calculate total, successful, failed, cache/db/new counts from items."""
        items = [
            BatchItemResponse.success_(
                url='https://a.com',
                short_code='a1',
                original_url='https://a.com',
                base_url=base_url,
                clicks=0,
                is_new=True,
                from_cache=False
            ),
            BatchItemResponse.success_(
                url='https://b.com',
                short_code='b1',
                original_url='https://b.com',
                base_url=base_url,
                clicks=5,
                is_new=False,
                from_cache=True
            ),
            BatchItemResponse.success_(
                url='https://c.com',
                short_code='c1',
                original_url='https://c.com',
                base_url=base_url,
                clicks=2,
                is_new=False,
                from_cache=False  # from DB
            ),
            BatchItemResponse.error_('https://d.com', 'Invalid')
        ]
        response = BatchCreateResponse.from_results(items)

        assert response.total == 4
        assert response.successful == 3
        assert response.failed == 1
        assert response.from_cache_count == 1
        assert response.from_db_count == 1  # successful, not new, not from cache
        assert response.new_count == 1
        assert len(response.items) == 4
        assert response.created_at is not None


# ------------------------------------------------------------------
# ServiceStatsResponse
# ------------------------------------------------------------------
class TestServiceStatsResponse:
    """Tests for ServiceStatsResponse DTO."""

    def test_to_dict(self):
        """Should convert ServiceStatsResponse to dictionary with rounded avg clicks."""
        
        now = datetime.now()
        popular = [
            StatsItemResponse(
                short_code='abc123',
                short_url='https://short.link/abc123',
                original_url='https://example.com',
                clicks=100,
                created_at=now
            )
        ]
        response = ServiceStatsResponse(
            total_urls=10,
            total_clicks=500,
            avg_clicks_per_url=50.0,
            popular_links=popular
        )
        data = response.to_dict()
        
        assert data['total_urls'] == 10
        assert data['total_clicks'] == 500
        assert data['avg_clicks_per_url'] == 50.0
        assert len(data['popular_links']) == 1
        link_data = data['popular_links'][0]
        assert link_data['short_code'] == 'abc123'
        assert link_data['clicks'] == 100
        assert 'created_at' in link_data


# ------------------------------------------------------------------
# TestExtendLinkInfoResponse
# ------------------------------------------------------------------
class TestExtendLinkInfoResponse:
    """Tests for ExtendedLinkInfoResponse DTO."""

    @pytest.fixture
    def sample_link(self):
        url_hash = UrlHash('a' * 64)
        short_code = ShortCode('abc123')
        original_url = OriginalUrl('https://example.com')
        link = Link.create(
            url_hash=url_hash,
            short_code=short_code,
            original_url=original_url
        )
        # override date for predictability
        link.created_at = datetime.now(timezone.utc) - timedelta(days=5)
        link.clicks = 20
        link.last_accessed = datetime.now(timezone.utc) - timedelta(days=1)
        return link
    
    def test_from_link_computes_correct_fields(self, sample_link):
        """Should compute age_days, clicks_per_day, last_access_days_ago correctly."""

        base_url = 'https://short.link'
        response = ExtendedLinkInfoResponse.from_link(
            sample_link, base_url, popular_threshold=100, recent_days=7
        )

        assert response.short_code == 'abc123'
        assert response.short_url == 'https://short.link/abc123'
        assert response.original_url == 'https://example.com'
        assert response.clicks == 20
        assert response.age_days == 5
        assert response.clicks_per_day == 4.0  # 20/5
        assert response.last_access_days_ago == 1
        assert response.is_popular is False  # threshold 100
        assert response.is_recent is True    # days=7

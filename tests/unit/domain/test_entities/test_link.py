from datetime import datetime, timedelta, timezone
from link_shortener.domain.entities.link import Link
from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.url_hash import UrlHash
import pytest


@pytest.fixture
def sample_link(valid_url_hash, valid_short_code, valid_original_url) -> Link:
    """Link with default parameters"""
    link = Link.create(
        url_hash=valid_url_hash,
        short_code=valid_short_code,
        original_url=valid_original_url
    )
    return link

# ------------------------------------------------------------------
# TestLink
# ------------------------------------------------------------------
class TestLink:
    """
    Tests for the Link domain entity and its business rules.
    """

    def test_create_with_custom_id(self, valid_url_hash, valid_short_code, valid_original_url):
        """Should create link with custom ID when provided."""
        
        custom_id = 'custom-123'
        link = Link.create(
            url_hash=valid_url_hash,
            short_code=valid_short_code,
            original_url=valid_original_url,
            link_id=custom_id
        )
        assert link.id == custom_id

    def test_create_link_sets_defaults(
        self,
        sample_link: Link,
        valid_url_hash: UrlHash, 
        valid_short_code: ShortCode, 
        valid_original_url: OriginalUrl
    ):
        """
        Should correctly initialize all fields via the factory method 'create'
        """

        assert sample_link.id is not None
        assert sample_link.url_hash == valid_url_hash
        assert sample_link.short_code == valid_short_code
        assert sample_link.original_url == valid_original_url
        assert sample_link.clicks == 0
        assert datetime.now(timezone.utc) - sample_link.created_at < timedelta(seconds=1)
        assert sample_link.last_accessed is None


    def test_increment_clicks_updates_count_and_timestamp(self, sample_link: Link):
        """
        Should increment click count and update last_accessed timestamp.
        """

        old_last_accessed = sample_link.last_accessed

        # Act
        sample_link.increment_clicks()

        assert sample_link.clicks == 1
        assert sample_link.last_accessed is not None
        assert sample_link.last_accessed != old_last_accessed
        assert datetime.now(timezone.utc) - sample_link.last_accessed < timedelta(seconds=1)
    
    
    @pytest.mark.parametrize('clicks, threshold, expected', [
        (150, 100, True),
        (99, 100, False),
        (100, 100, False)
    ])
    def test_is_popular(self, clicks, threshold, expected, sample_link: Link):
        """
        Should correctly determine if a link is popular based on click threshold. 
        """
        sample_link.clicks = clicks

        assert sample_link.is_popular(threshold) == expected
    
    
    @pytest.mark.parametrize('days_ago, days, expected', [
        (3, 7, True),
        (10, 7, False),
        (7, 7, True)
    ])
    def test_is_recent(self, days_ago, days, expected, sample_link: Link):
        """
        Should correctly determine if a link is recent based on creation date.
        """
        sample_link.created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)

        assert sample_link.is_recent(days) == expected
    
    
    def test_equality_based_on_id(
        self, valid_url_hash, valid_short_code, valid_original_url
    ):
        """Should consider links equal if they have the same ID."""
        
        link1 = Link.create(
            url_hash=valid_url_hash,
            short_code=valid_short_code,
            original_url=valid_original_url
        )
        link2 = Link.create(
            url_hash=valid_url_hash,
            short_code=valid_short_code,
            original_url=valid_original_url
        )
        
        link2.id = link1.id  # force ids to match
        
        assert link1 == link2
        assert hash(link1) == hash(link2)

    
    def test_inequality_different_ids(
        self, valid_url_hash, valid_short_code, valid_original_url
    ):
        """Should consider links different if they have different IDs."""
        
        link1 = Link.create(
            url_hash=valid_url_hash,
            short_code=valid_short_code,
            original_url=valid_original_url
        )
        link2 = Link.create(
            url_hash=valid_url_hash,
            short_code=valid_short_code,
            original_url=valid_original_url
        )
        assert link1 != link2
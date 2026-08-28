from datetime import datetime, timedelta, timezone
from link_shortener.domain.entities.link import Link
from link_shortener.domain.exceptions import ValidationError
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


    @pytest.mark.parametrize("ttl_seconds", [
        251_616_310_632,   # where timedelta arithmetic first gives up
        10 ** 12,
        10 ** 30,
    ])
    def test_a_lifetime_with_no_date_behind_it_is_refused(
        self, ttl_seconds, valid_url_hash, valid_short_code, valid_original_url
    ):
        """
        The floor under ``MAX_TTL_SECONDS``, which is configurable.

        Adding this to ``datetime.now()`` raises ``OverflowError`` -- not a
        subclass of ``ValueError``, so nothing between here and the HTTP
        layer caught it and a two-field request body came back 500.
        """
        with pytest.raises(ValidationError, match="ttl_seconds"):
            Link.create(
                url_hash=valid_url_hash,
                short_code=valid_short_code,
                original_url=valid_original_url,
                ttl_seconds=ttl_seconds,
            )

    def test_an_ordinary_lifetime_still_produces_a_date(
        self, valid_url_hash, valid_short_code, valid_original_url
    ):
        link = Link.create(
            url_hash=valid_url_hash,
            short_code=valid_short_code,
            original_url=valid_original_url,
            ttl_seconds=3600,
        )

        assert link.expires_at is not None

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


class TestTheMomentOfExpiryItself:
    """Expiry is inclusive: at the stroke, the link is already gone.

    The comparison is ``>=``, and the only clock reading that tells that
    from ``>`` is the expiry itself. Measured before this test: flipping
    it left the whole suite green, so a link would have gone on
    redirecting for as long as the two stamps were equal.
    """

    def _at(self, monkeypatch, moment):
        """Make ``datetime.now`` inside the entity answer ``moment``."""
        import link_shortener.domain.entities.link as module

        class FixedClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return moment

        monkeypatch.setattr(module, "datetime", FixedClock)

    def test_a_link_whose_expiry_is_now_has_expired(
        self, monkeypatch, sample_link: Link
    ):
        expiry = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
        sample_link.expires_at = expiry
        self._at(monkeypatch, expiry)

        assert sample_link.is_expired() is True

    def test_one_microsecond_earlier_it_has_not(
        self, monkeypatch, sample_link: Link
    ):
        expiry = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
        sample_link.expires_at = expiry
        self._at(monkeypatch, expiry - timedelta(microseconds=1))

        assert sample_link.is_expired() is False

    def test_a_link_with_no_expiry_never_expires(
        self, monkeypatch, sample_link: Link
    ):
        sample_link.expires_at = None
        self._at(monkeypatch, datetime(2099, 1, 1, tzinfo=timezone.utc))

        assert sample_link.is_expired() is False


class TestComparedWithSomethingThatIsNotALink:
    """``__eq__`` answers False rather than raising or deferring.

    The branch was unreached: every equality test above compares two
    links. Written to return ``NotImplemented``, or to read ``.id`` off
    whatever it was handed, this raises instead -- and the caller is
    ``in`` on a list, where an exception is not the answer anybody wants.
    """

    @pytest.mark.parametrize(
        "other", ["not-a-link", 42, None, object()],
        ids=["a string", "a number", "nothing", "a bare object"],
    )
    def test_it_is_not_equal_and_does_not_raise(self, sample_link: Link, other):
        assert sample_link != other
        assert (sample_link == other) is False

    def test_a_link_is_still_findable_among_them(self, sample_link: Link):
        """The caller this protects: a membership test over a mixed list."""
        assert sample_link in ["not-a-link", 42, sample_link]

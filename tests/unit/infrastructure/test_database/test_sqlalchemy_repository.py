from link_shortener.domain.entities.link import Link
from link_shortener.infrastructure.database.repositories.sqlalchemy_link_repository import SQLAlchemyLinkRepository
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.url_hash import UrlHash
from link_shortener.domain.value_objects.original_url import OriginalUrl
import pytest


@pytest.fixture
def repo(db_manager):
    """
    Provide a SQLAlchemyLinkRepository 
    with a database session.
    """
    return SQLAlchemyLinkRepository(db_manager)


# ------------------------------------------------------------------
# TestRedisLinkCache
# ------------------------------------------------------------------
class TestSQLAlchemyLinkRepository:
    """Tests for SQLAlchemyLinkRepository."""

    def test_save(self, repo, sample_link):
        """Should save a link to the database."""

        # Act
        repo.save(sample_link)

        # Assert
        assert repo.find_by_code(sample_link.short_code) == sample_link

    def test_save_many(self, repo, sample_link):
        """Should save multiple links at once."""
        
        # Arrange
        link_2 = Link.create(
            url_hash=UrlHash("d"*64),
            short_code=ShortCode("code789"),
            original_url=OriginalUrl("https://test-2.com")
        )

        # Act
        repo.save_many([sample_link, link_2])

        # Assert
        assert repo.find_by_code(sample_link.short_code) == sample_link
        assert repo.find_by_code(link_2.short_code) == link_2

    def test_find_by_code(self, repo, sample_link):
        """Should find a link by its short code."""

        saved = repo.save(sample_link)
        assert saved.id == sample_link.id

        found = repo.find_by_code(sample_link.short_code)
        assert found == sample_link

    def test_find_by_codes_empty(self, repo):
        """
        Should return empty dict 
        when given empty list of codes.
        """

        result = repo.find_by_codes([])
        assert result == {}

    def test_find_by_codes(self, repo, sample_link):
        """Should find multiple links by their short codes."""
        
        # Arrange
        repo.save(sample_link)
        another_code = ShortCode('code123')

        # Act
        result = repo.find_by_codes([sample_link.short_code, another_code])

        # Assert
        assert result[sample_link.short_code] == sample_link
        assert result[another_code] is None

    def test_find_by_hash(self, repo, sample_link):
        """Should find a link by its URL hash."""
        
        repo.save(sample_link)

        found = repo.find_by_hash(sample_link.url_hash)

        assert found == sample_link

    def test_find_by_hashes_empty(self, repo):
        """
        Should return empty dict 
        when given empty list of hashes.
        """

        result = repo.find_by_hashes([])
        assert result == {}

    def test_find_by_hashes(self, repo, sample_link):
        """Should find multiple links by their hashes."""

        # Arrange
        repo.save(sample_link)
        another_hash = UrlHash('b'* 64)

        # Act
        result = repo.find_by_hashes([sample_link.url_hash, another_hash])

        # Assert
        assert result[sample_link.url_hash] == sample_link
        assert result[another_hash] is None

    def test_increment_clicks_nonexistent(self, repo):
        """
        Should not raise error 
        when incrementing clicks for non-existent link.
        """

        # не должно падать
        repo.increment_clicks(ShortCode('nonexist'))
        assert repo.find_by_code(ShortCode('nonexist')) is None

    def test_increment_clicks(self, repo, sample_link):
        """Should increment clicks and update last_accessed."""

        # Arrange
        repo.save(sample_link)
        old_clicks = sample_link.clicks
        
        # Acts
        repo.increment_clicks(sample_link.short_code)
        updated = repo.find_by_code(sample_link.short_code)

        # Assert
        assert updated.clicks == old_clicks + 1
        assert updated.last_accessed is not None

    def test_increment_clicks_batch_empty(self, repo):
        """
        Should not raise error 
        when incrementing batch with empty list.
        """
        repo.increment_clicks_batch([])  # просто не падает

    def test_increment_clicks_batch(self, repo, sample_link):
        """Should increment clicks for multiple links in batch"""

        # Arrange
        link_2 = Link.create(
            url_hash=UrlHash("c"*64),
            short_code=ShortCode("code456"),
            original_url=OriginalUrl("https://test-2.com")
        )
        link_2.clicks = 5
        repo.save_many([sample_link, link_2])

        # Act
        repo.increment_clicks_batch([sample_link.short_code, link_2.short_code])
        updated_results = repo.find_by_codes([sample_link.short_code, link_2.short_code])

        # Assert
        assert updated_results[sample_link.short_code].url_hash == sample_link.url_hash
        assert updated_results[sample_link.short_code].clicks == 1
        assert updated_results[link_2.short_code].url_hash == link_2.url_hash
        assert updated_results[link_2.short_code].clicks == link_2.clicks + 1

    def test_get_stats(self, repo, sample_link):
        """Should return correct service statistics."""

        # Arrange
        sample_link.clicks = 150
        link2 = Link.create(
            url_hash=UrlHash("e"*64),
            short_code=ShortCode("code000"),
            original_url=OriginalUrl("https://test-2.com")
        )
        link2.clicks = 101
        repo.save_many([sample_link, link2])

        # Act
        stats = repo.get_stats()

        # Assert
        assert stats["total_urls"] == 2
        assert stats["total_clicks"] == 251 # sample_link 150 + link2 101 = 251
        assert len(stats["popular_links"]) == 2 
        # Проверка порядка (по убыванию clicks)
        assert stats["popular_links"][0].short_code == sample_link.short_code
        assert stats["popular_links"][0].clicks == 150
        assert stats["popular_links"][1].short_code == link2.short_code

    def test_get_stats_empty(self, repo):
        """
        Should return zeros and empty list 
        when no links exist.
        """
        
        stats = repo.get_stats()
        assert stats['total_urls'] == 0
        assert stats['total_clicks'] == 0
        assert stats['popular_links'] == []
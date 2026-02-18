from unittest.mock import Mock
from link_shortener.application.dtos.responses import ShortLinkResponse
from link_shortener.application.use_cases.create_short_link import CreateShortLinkUseCase
from link_shortener.domain.entities.link import Link
from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.url_hash import UrlHash
import pytest


@pytest.fixture
def use_case(
    mock_link_repository, mock_link_cache, shortening_policy, mock_logger, base_url
): 
    """Fixture for CreateShortLinkUseCase."""

    use_case = CreateShortLinkUseCase(
        repository=mock_link_repository,
        cache=mock_link_cache,
        shortening_policy=shortening_policy,
        base_url=base_url,
        logger=mock_logger,
        max_collision_attempts=3
    )

    return use_case

@pytest.fixture
def sample_link(valid_url_hash, valid_short_code, valid_original_url):
    """Fixture for a Link (as if from cache or DB)."""
    
    return Link.create(
        url_hash=valid_url_hash,
        short_code=valid_short_code,
        original_url=valid_original_url
    )


# ------------------------------------------------------------------
# TestCreateShortLinkUseCase
# ------------------------------------------------------------------
class TestCreateShortLinkUseCase:
    """Tests for the CreateShortLinkUseCase."""

    def test_happy_path_creates_new_link(
        self, use_case, sample_link, mock_link_cache, mock_link_repository
    ):
        """Should create a new link when not found in cache or DB."""
        
        url = sample_link.original_url.value
        
        mock_link_cache.get_by_hash.return_value = None
        mock_link_repository.find_by_hash.return_value = None
        mock_link_repository.find_by_code.return_value = None

        mock_link_repository.save.return_value = sample_link

        # Act
        response = use_case.execute(url)

        # Assert
        assert isinstance(response, ShortLinkResponse)
        assert response.is_new is True
        assert response.from_cache is False
        assert response.short_code == sample_link.short_code.value
        assert response.original_url == url

        mock_link_cache.get_by_hash.assert_called_once()
        mock_link_repository.find_by_hash.assert_called_once()
        mock_link_repository.find_by_code.assert_called()
        mock_link_repository.save.assert_called_once()
        mock_link_cache.save.assert_called_once_with(sample_link)

    def test_cache_hit_returns_cached_link(
        self, use_case, sample_link, mock_link_repository, mock_link_cache
    ):
        """Should return link from cache without touching DB."""
        
        url = sample_link.original_url.value
        mock_link_cache.get_by_hash.return_value = sample_link

        # Act
        response = use_case.execute(url)

        assert isinstance(response, ShortLinkResponse)
        assert response.from_cache is True
        assert response.is_new is False
        mock_link_repository.find_by_hash.assert_not_called()
        mock_link_repository.find_by_code.assert_not_called()
        mock_link_repository.save.assert_not_called()
        mock_link_cache.save.assert_not_called()

    def test_db_hit_returns_from_db_and_caches(
        self, use_case, sample_link, mock_link_cache, mock_link_repository 
    ):
        """Should return link from DB and save it to cache."""

        url = sample_link.original_url.value
        mock_link_cache.get_by_hash.return_value = None
        mock_link_repository.find_by_hash.return_value = sample_link

        # Act
        response = use_case.execute(url)

        assert isinstance(response, ShortLinkResponse)
        assert response.is_new is False
        assert response.from_cache is False
        mock_link_cache.save.assert_called_once_with(sample_link)
        mock_link_repository.save.assert_not_called()
        mock_link_repository.find_by_code.assert_not_called()

    def test_invalid_url_raises_value_error(
        self, use_case, mock_link_cache, mock_link_repository
    ):
        """
        Should raise ValueError for invalid URL
        without calling external services.
        """
        
        invalid_url = 'bad-url'
        with pytest.raises(ValueError, match='Invalid URL'):
            use_case.execute(invalid_url)
        
        mock_link_cache.get_by_hash.assert_not_called()
        mock_link_repository.find_by_hash.assert_not_called()
        mock_link_repository.find_by_code.assert_not_called()

    def test_max_attempts_exceeded_raises_runtime_error(
        self, use_case, mock_link_cache, mock_link_repository
    ):
        """
        Should raise RuntimeError when code generation fails after max attempts.
        """
        url = "https://test.com"
        mock_link_cache.get_by_hash.return_value = None
        mock_link_repository.find_by_hash.return_value = None

        existing_link = Mock(spec=Link)
        existing_link.url_hash = UrlHash('b' * 64)  # different hash

        # always collision
        mock_link_repository.find_by_code.return_value = existing_link

        with pytest.raises(RuntimeError, match="Failed to generate unique short code after multiple attempts"):
            use_case.execute(url)

        assert mock_link_repository.find_by_code.call_count == use_case.max_collision_attempts
        mock_link_repository.save.assert_not_called()

    def test_collision_handling_retries_generation(
        self, use_case, mock_link_cache, mock_link_repository, shortening_policy
    ):
        """
        Should retry code generation when generated code collides with existing link
        and eventually succeed.
        """
        url = "https://test.com"
        original_url = OriginalUrl(url)
        url_hash = shortening_policy.calculate_hash(original_url)

        existing_link = Mock(spec=Link)
        existing_link.url_hash = UrlHash('b' * 64)  # different hash
        existing_link.short_code = ShortCode('abc123')  # first generated code

        mock_link_cache.get_by_hash.return_value = None
        mock_link_repository.find_by_hash.return_value = None

        call_count = 0
        def find_by_code_side_effect(code):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return existing_link  # collision
            return None
        mock_link_repository.find_by_code.side_effect = find_by_code_side_effect

        # Создаём реальный объект Link для возврата из save
        saved_link = Link.create(
            url_hash=url_hash,
            short_code=ShortCode('unique123'),  # final unique code
            original_url=original_url
        )
        mock_link_repository.save.return_value = saved_link

        response = use_case.execute(url)

        assert response.short_code == 'unique123'
        assert response.is_new is True
        assert mock_link_repository.find_by_code.call_count == 3
        mock_link_repository.save.assert_called_once()
        mock_link_cache.save.assert_called_once_with(saved_link)
    

    def test_collision_with_same_hash(
        self, use_case, mock_link_cache, mock_link_repository, shortening_policy
    ):
        """
        Если найденная в БД ссылка имеет тот же хэш (т.е. это та же ссылка),
        use case должен вернуть её без повторной генерации кода.
        """
        url = "https://test.com"
        original_url = OriginalUrl(url)
        url_hash = shortening_policy.calculate_hash(original_url)
        short_code = shortening_policy.generate_code_for_url(original_url)

        existing_link = Link.create(
            url_hash=url_hash,
            short_code=short_code,
            original_url=original_url
        )

        mock_link_cache.get_by_hash.return_value = None
        mock_link_repository.find_by_hash.return_value = existing_link
        # find_by_code не должен вызываться, т.к. мы нашли по хэшу
        mock_link_repository.find_by_code.return_value = None  # не важно

        response = use_case.execute(url)

        assert response.short_code == short_code.value
        assert response.is_new is False
        mock_link_cache.save.assert_called_once_with(existing_link)
        mock_link_repository.find_by_code.assert_not_called()
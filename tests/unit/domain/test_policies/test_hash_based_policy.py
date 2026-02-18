from link_shortener.domain.policies.impl.hash_based import HashBasedShorteningPolicy
from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.url_hash import UrlHash
import pytest


# ------------------------------------------------------------------
# TestHashBasedShorteningPolicy
# ------------------------------------------------------------------
class TestHashBasedShorteningPolicy:
    """Tests for the hashbased shortening policy implementation."""

    @pytest.fixture
    def policy(self) -> HashBasedShorteningPolicy:
        """Fixture with default code length 7."""
        return HashBasedShorteningPolicy(code_length=7)
    
    def test_calculate_hash_returns_url_hash_object(
        self, policy: HashBasedShorteningPolicy, valid_original_url: OriginalUrl,
    ):
        """Should generate a UrlHash object of correct length."""
        
        url_hash = policy.calculate_hash(valid_original_url)

        assert isinstance(url_hash, UrlHash)
        assert len(url_hash.value) == 64
    
    def test_calculate_hash_normalize(self, policy: HashBasedShorteningPolicy):
        """Should return the same hash for different representations of the same URL."""
        
        url_1 = OriginalUrl('https://Test.COM/path')
        url_2 = OriginalUrl('https://test.com/path')
        
        hash_1 = policy.calculate_hash(url_1)
        hash_2 = policy.calculate_hash(url_2)

        assert hash_1 == hash_2
    
    def test_generate_code_returns_short_code_of_correct_length(self, policy: HashBasedShorteningPolicy):
        """Should generate a ShortCode with the configured length (default 7)."""
        code = policy.generate_code('test_code')
        
        assert isinstance(code, ShortCode)
        assert len(code.value) == 7
    
    @pytest.mark.parametrize('code_length', [6, 8, 10])
    def test_code_length_respected(self, code_length):
        """Should respect the configured code length."""

        policy = HashBasedShorteningPolicy(code_length=code_length)

        code = policy.generate_code('test_code')

        assert len(code.value) == code_length
    
    def test_generate_code_for_url_uses_normalized_url(
        self, policy: HashBasedShorteningPolicy, valid_original_url: OriginalUrl
    ):
        """Should generate code based on the normalized URL."""
        
        code1 = policy.generate_code_for_url(valid_original_url)
        code2 = policy.generate_code(valid_original_url.normalize())

        assert code1 == code2
    
    def test_generate_unique_code_with_attempt_changes_code(
        self, policy: HashBasedShorteningPolicy, valid_original_url: OriginalUrl
    ):
        """
        Should generate different codes when attempt > 0 (salt added).
        """
        code0 = policy.generate_unique_code(valid_original_url, attempt=0)
        code1 = policy.generate_unique_code(valid_original_url, attempt=1)

        assert code0 != code1
    
    def test_policy_raises_on_invalid_code_length(self):
        """
        Should raise ValueError if code_length is outside the allowed range (6-10).
        """
        with pytest.raises(ValueError, match='code_length must be between'):
            HashBasedShorteningPolicy(code_length=5)

        with pytest.raises(ValueError, match='code_length must be between'):
            HashBasedShorteningPolicy(code_length=11)

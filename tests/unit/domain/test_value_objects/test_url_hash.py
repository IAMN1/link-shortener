import pytest
from link_shortener.domain.value_objects.url_hash import UrlHash
from link_shortener.domain.exceptions import ValidationError


# ------------------------------------------------------------------
# TestUrlHash
# ------------------------------------------------------------------
class TestUrlHash:
    """Tests for the UrlHash value object."""

    @pytest.mark.parametrize('valid_hash', [
        'a' * 64,
        'b' * 64,
        '0123456789abcdef' * 4
    ])
    def test_valid_hash_creates_object(self, valid_hash):
        """Should create a UrlHash object from a valid hex string (64 chars)."""
        
        url_hash = UrlHash(valid_hash)

        assert url_hash.value == valid_hash
    
    @pytest.mark.parametrize('invalid_hash, expected_error', [
        ('abc', 'Invalid hash format'),     # too short
        ('a' * 63, 'Invalid hash format'),  # 63 chars
        ('a' * 65, 'Invalid hash format'),  # 65 chars
        ('g' * 64, 'Invalid hash format'),  # not hex
        ('', 'Invalid hash format'),        # empty
    ])
    def test_invalid_hash_raises_value_error(self, invalid_hash, expected_error):
        """Should raise ValidationError for invalid hash strings."""
        
        with pytest.raises(ValidationError, match=expected_error):
            UrlHash(invalid_hash)
    
    def test_str_representation(self, valid_url_hash_str):
        """String representation should equal the hash value."""
        
        url_hash = UrlHash(valid_url_hash_str)

        assert str(url_hash) == valid_url_hash_str
    
    def test_equality(self, valid_url_hash_str):
        """Two UrlHash objects with the same value should be equal."""
        
        hash1 = UrlHash(valid_url_hash_str)
        hash2 = UrlHash(valid_url_hash_str)

        assert hash1 == hash2
        assert hash1 is not hash2
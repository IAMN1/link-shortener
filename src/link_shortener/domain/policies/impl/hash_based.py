import base64
import hashlib

from link_shortener.domain.policies.shortening_policy import ShorteningPolicy
from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.url_hash import UrlHash


class HashBasedShorteningPolicy(ShorteningPolicy):
    """
    Deterministic shortening policy based on hashing.

    Same URL always produces the same short code (collisions handled by caller).
    Uses SHA-256 hash and base64url encoding.
    """

    def __init__(self, code_length: int = 7, min_length: int = 6, max_length: int = 10):
        """
        Initialize the policy with length constraints.

        Args:
            code_length: Desired length of the short code.
            min_length: Minimum allowed length.
            max_length: Maximum allowed length.

        Raises:
            ValueError: If code_length is not within [min_length, max_length].
        """

        if not (min_length <= code_length <= max_length):
            raise ValueError(
                f"code_length must be between {min_length} and {max_length}"
            )

        self.code_length = code_length
        self.min_length = min_length
        self.max_length = max_length

    def calculate_hash(self, original_url: OriginalUrl) -> UrlHash:
        """
        Compute a SHA-256 hash of the normalized URL for deduplication.

        Args:
            original_url: The original URL to hash.

        Returns:
            UrlHash value object containing the hex digest.
        """

        # Нормализация URL для дедупликации
        normalized = original_url.normalize()
        url_hash = hashlib.sha256(normalized.encode()).hexdigest()

        return UrlHash(url_hash)

    def generate_code(self, input_string: str) -> ShortCode:
        """
        Generate a short code deterministically from an input string.

        The method uses base64url encoding of a truncated SHA-256 hash.
        The result is trimmed to `code_length`.

        Args:
            input_string: String to base the code on (e.g., normalized URL).

        Returns:
            ShortCode value object.
        """
        target_len = max(self.code_length, self.min_length)
        need_bytes = (target_len * 6 + 7) // 8
        hash_bytes = hashlib.sha256(input_string.encode()).digest()[:need_bytes]
        short_bytes = base64.urlsafe_b64encode(hash_bytes)
        short_code = short_bytes.decode().rstrip("=")[: self.code_length]

        return ShortCode(short_code)

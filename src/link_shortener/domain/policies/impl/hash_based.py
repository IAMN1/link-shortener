import base64
import hashlib

from link_shortener.domain.policies.shortening_policy import ShorteningPolicy
from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.url_hash import UrlHash


class HashBasedShorteningPolicy(ShorteningPolicy):
    """
    Deterministic shortening policy based on hashing with optional pepper.

    Same URL always produces the same short code (collisions handled by caller).
    Uses SHA-256 hash and base64url encoding. A pepper can be provided to
    increase entropy and prevent code predictability.
    """

    def __init__(self, code_length: int = 7, min_length: int = 6, max_length: int = 10, pepper: str = ""):
        """
        Initialize the policy with length constraints and an optional pepper.

        Args:
            code_length: Desired length of the short code.
            min_length: Minimum allowed length.
            max_length: Maximum allowed length.
            pepper: Secret string added to input before hashing to increase entropy.
                Should be set via environment variable in production.

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
        self.pepper = pepper

    def calculate_hash(self, original_url: OriginalUrl) -> UrlHash:
        """
        Compute a SHA-256 hash of the normalized URL for deduplication.

        This hash is used to detect duplicate URLs and does not use pepper,
        as it must be deterministic and consistent across instances.

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
        The result is trimmed to `code_length`. If a pepper is configured,
        it is appended to the input string before hashing to make codes
        harder to guess.

        Args:
            input_string: String to base the code on (e.g., normalized URL).

        Returns:
            ShortCode value object.
        """
        # Append pepper to increase entropy and prevent predictability
        salted = input_string + self.pepper

        target_len = max(self.code_length, self.min_length)
        need_bytes = (target_len * 6 + 7) // 8
        hash_bytes = hashlib.sha256(salted.encode()).digest()[:need_bytes]
        short_bytes = base64.urlsafe_b64encode(hash_bytes)
        short_code = short_bytes.decode().rstrip("=")[: self.code_length]

        return ShortCode(short_code)

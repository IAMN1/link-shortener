"""SHA-256 implementation of HashCalculator."""

import hashlib
from link_shortener.domain import HashCalculator, OriginalUrl, UrlHash


class SHA256HashCalculator(HashCalculator):
    """
    Computes a SHA-256 hash of the normalized URL for deduplication.

    This implementation is deterministic and does not use any external secret,
    ensuring that the same URL always produces the same hash across all
    service instances.
    """

    def calculate(self, original_url: OriginalUrl):
        """
        Compute SHA-256 hash of the normalized URL and return as hex digest.

        Args:
            original_url: The original URL value object.

        Returns:
            UrlHash containing the 64-character hex digest.
        """
        normalized = original_url.normalize()
        hash_bytes = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return UrlHash(hash_bytes)

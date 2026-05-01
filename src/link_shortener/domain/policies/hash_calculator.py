"""Abstract interface for calculating a stable hash from an OriginalUrl."""

from abc import ABC, abstractmethod

from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.domain.value_objects.url_hash import UrlHash


class HashCalculator(ABC):
    """
    Domain policy for computing a hash of a URL used for deduplication.

    The hash must be deterministic and consistent across all instances of the service.
    Implementations may use different hashing algorithms (SHA-256, SHA-3, etc.).
    This abstraction belongs to the domain layer; concrete implementations reside
    in the infrastructure layer.
    """

    @abstractmethod
    def calculate(self, original_url: OriginalUrl) -> UrlHash:
        """
        Compute a hash of the normalized URL.

        Args:
            original_url: The original URL value object (already validated).

        Returns:
            UrlHash: A value object containing the hash string (e.g., hex digest).
        """
        raise NotImplementedError

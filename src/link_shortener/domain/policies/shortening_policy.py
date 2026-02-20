from abc import ABC, abstractmethod

from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.url_hash import UrlHash


class ShorteningPolicy(ABC):
    """
    Domain policy defining business rules 
        for short code and hash generation.
    """

    @abstractmethod
    def calculate_hash(self, original_url: OriginalUrl) -> UrlHash:
        """
        Compute a hash of the URL for deduplication purposes.

        Args:
            original_url: The original URL.

        Returns:
            UrlHash value object.
        """
        pass

    @abstractmethod
    def generate_code(self, input_str: str) -> ShortCode:
        """
        Generate a short code from an arbitrary input string.

        Args:
            input_str: String to generate code from.

        Returns:
            ShortCode value object.
        """
        pass

    def generate_code_for_url(self, original_url: OriginalUrl) -> ShortCode:
        """
        Convenience method: generate a short code directly 
            from a URL (uses normalized string).

        Args:
            original_url: The original URL.

        Returns:
            ShortCode value object.
        """
        return self.generate_code(original_url.normalize())

    def generate_unique_code(
        self, original_url: OriginalUrl, attempt: int = 0
    ) -> ShortCode:
        """
        Generate a code with an optional salt to resolve collisions.

        When attempt > 0, a suffix is appended to the normalized URL before hashing,
        producing a different code without altering the original URL.

        Args:
            original_url: The original URL.
            attempt: Collision attempt counter (0 = no salt).

        Returns:
            ShortCode value object (potentially different if attempt > 0).
        """
        base = original_url.normalize()
        if attempt == 0:
            return self.generate_code(base)
        salted = f"{base}#collision_{attempt}"
        return self.generate_code(salted)

from abc import ABC, abstractmethod
from typing import Optional

from link_shortener.domain import ShortCode


class RedirectCache(ABC):
    """
    Interface for caching original URLs for fast redirects (L1 cache).

    This cache stores only the mapping from short code to original URL,
    without full Link objects, for maximum performance.
    """

    @abstractmethod
    def get_original_url(self, short_code: ShortCode) -> Optional[str]:
        """
        Retrieve the original URL for a given short code (fast path).

        Args:
            short_code (ShortCode): Short code value object.

        Returns:
            Optional[str]: Original URL as string if found, else None.
        """
        ...

    @abstractmethod
    def save_original_url(self, short_code: ShortCode, original_url: str) -> None:
        """
        Store the original URL for a short code 
            (for future fast redirects).

        Args:
            short_code (ShortCode): Short code value object.
            original_url (str): Original URL string.
        """
        ...

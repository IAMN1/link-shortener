from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from link_shortener.domain.entities.link import Link
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.url_hash import UrlHash


class LinkRepository(ABC):
    """Interface for link storage operations."""

    @abstractmethod
    def save(self, link: Link) -> Link:
        """Save a single link to the repository."""
        pass

    @abstractmethod
    def save_many(self, links: list[Link]) -> List[Link]:
        """Bulk save multiple links."""
        pass

    @abstractmethod
    def find_by_code(self, short_code: ShortCode) -> Optional[Link]:
        """Find a link by its short code."""
        pass

    @abstractmethod
    def find_by_codes(
        self, short_codes: List[ShortCode]
    ) -> Dict[ShortCode, Optional[Link]]:
        """
        Bulk find links by short codes; 
            returns a dict mapping code -> link or None.
        """
        pass

    @abstractmethod
    def find_by_hash(self, url_hash: UrlHash) -> Optional[Link]:
        """Find a link by its URL hash (for deduplication)."""
        pass

    @abstractmethod
    def find_by_hashes(
        self, url_hashes: List[UrlHash]
    ) -> Dict[UrlHash, Optional[Link]]:
        """
        Bulk find links by URL hashes; 
            returns dict mapping hash -> link or None.
        """
        pass

    @abstractmethod
    def increment_clicks(self, short_code: ShortCode) -> None:
        """Increment click count for a given short code."""
        pass

    @abstractmethod
    def increment_clicks_batch(self, short_codes: List[ShortCode]) -> None:
        """Bulk increment click counts for multiple short codes."""
        pass

    @abstractmethod
    def get_stats(self) -> dict:
        """
        Retrieve service statistics.

        Returns:
            dict with keys: 
                - 'total_urls', 
                - 'total_clicks', 
                - 'popular_links' (list of Link).
        """
        pass

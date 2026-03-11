from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from link_shortener.domain.entities.link import Link
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.url_hash import UrlHash


class LinkRepository(ABC):
    """Interface for link storage operations."""

    @abstractmethod
    def save(self, link: Link) -> Link:
        """
        Save a single link to the repository.

        Args:
            link: Link entity to save.

        Returns:
            The saved Link (may include generated fields).
        """
        pass

    @abstractmethod
    def save_many(self, links: list[Link]) -> List[Link]:
        """
        Bulk save multiple links.

        Args:
            links: List of Link entities to save.

        Returns:
            List of saved Links.
        """
        pass

    @abstractmethod
    def find_by_code(self, short_code: ShortCode) -> Optional[Link]:
        """
        Find a link by its short code.

        Args:
            short_code: Short code value object.

        Returns:
            Link if found, else None.
        """
        pass

    @abstractmethod
    def find_by_codes(
        self, short_codes: List[ShortCode]
    ) -> Dict[ShortCode, Optional[Link]]:
        """
        Bulk find links by short codes.

        Args:
            short_codes: List of short code value objects.

        Returns:
            Dictionary mapping each code to either the found Link or None.
        """
        pass

    @abstractmethod
    def find_by_hash(self, url_hash: UrlHash) -> Optional[Link]:
        """
        Find a link by its URL hash (for deduplication).

        Args:
            url_hash: URL hash value object.

        Returns:
            Link if found, else None.
        """
        pass

    @abstractmethod
    def find_by_hashes(
        self, url_hashes: List[UrlHash]
    ) -> Dict[UrlHash, Optional[Link]]:
        """
        Bulk find links by URL hashes.

        Args:
            url_hashes: List of URL hash value objects.

        Returns:
            Dictionary mapping each hash to either the found Link or None.
        """
        pass

    @abstractmethod
    def increment_clicks(self, short_code: ShortCode) -> None:
        """
        Increment click count for a given short code.

        Args:
            short_code: Short code of the link to increment.
        """
        pass

    @abstractmethod
    def increment_clicks_batch(self, short_codes: List[ShortCode]) -> None:
        """
        Bulk increment click counts for multiple short codes.

        Args:
            short_codes: List of short codes.
        """
        pass

    @abstractmethod
    def get_stats(self) -> dict:
        """
        Retrieve service statistics.

        Returns:
            Dictionary with keys:
                - 'total_urls': total number of shortened URLs.
                - 'total_clicks': sum of all clicks.
                - 'popular_links': list of Link objects (most popular up to 10).
        """
        pass

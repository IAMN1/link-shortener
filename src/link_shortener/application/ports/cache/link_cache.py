from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from link_shortener.domain import Link, ShortCode, UrlHash


class LinkCache(ABC):
    """
    Interface for caching Link objects.

    Supports single and batch operations for both short codes and URL hashes.
    This cache is used for full link objects (L2 cache).
    """

    @abstractmethod
    def get_by_code(self, short_code: ShortCode) -> Optional[Link]:
        """
        Retrieve a link by its short code.

        Args:
            short_code (ShortCode): The short code value object.

        Returns:
            Optional[Link]: Link if found, else None.
        """
        pass

    @abstractmethod
    def get_by_hash(self, url_hash: UrlHash) -> Optional[Link]:
        """
        Retrieve a link by its URL hash (for deduplication).

        Args:
            url_hash (UrlHash): The URL hash value object.

        Returns:
            Optional[Link]: Link if found, else None.
        """
        pass

    @abstractmethod
    def get_by_hashes(self, url_hashes: List[UrlHash]) -> Dict[UrlHash, Optional[Link]]:
        """
        Bulk retrieve links by multiple URL hashes.

        Args:
            url_hashes (List[UrlHash]): List of URL hash value objects.

        Returns:
            Dict[UrlHash, Optional[Link]]: Dictionary mapping each hash 
                to either the found Link or None.
        """
        pass

    @abstractmethod
    def save(self, link: Link) -> None:
        """
        Store a single link in the cache.

        The implementation should store the link under appropriate keys
        (e.g., by short code and by hash) and set TTL.

        Args:
            link (Link): The Link to cache.
        """
        pass

    @abstractmethod
    def save_many(self, links: List[Link]) -> None:
        """
        Bulk store multiple links.

        Args:
            links (List[Link]): List of Link objects to cache.
        """
        pass

    @abstractmethod
    def delete(self, short_code: ShortCode) -> None:
        """
        Remove a link from the cache by its short code.

        Args:
            short_code (ShortCode): Short code of the link to delete.
        """
        pass

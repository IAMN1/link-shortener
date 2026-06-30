from abc import ABC, abstractmethod
from datetime import datetime
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
        ...

    @abstractmethod
    def save_many(self, links: list[Link]) -> List[Link]:
        """
        Bulk save multiple links.

        Args:
            links: List of Link entities to save.

        Returns:
            List of saved Links.
        """
        ...

    @abstractmethod
    def find_by_code(self, short_code: ShortCode) -> Optional[Link]:
        """
        Find a link by its short code.

        Args:
            short_code: Short code value object.

        Returns:
            Link if found, else None.
        """
        ...

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
        ...

    @abstractmethod
    def find_by_hash(self, url_hash: UrlHash) -> Optional[Link]:
        """
        Find a link by its URL hash (for deduplication).

        Args:
            url_hash: URL hash value object.

        Returns:
            Link if found, else None.
        """
        ...
    
    @abstractmethod
    def find_by_owner(self, user_id: str, offset: int = 0, limit: int = 50) -> List[Link]:
        """
        Retrieve links owned by a specific user.

        Args:
            user_id: UUID of the link owner.
            offset: Number of links to skip (default 0).
            limit: Maximum number of links to return (default 50).

        Returns:
            List of Link entities belonging to the user (may be empty).
        """
        ...

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
        ...

    @abstractmethod
    def increment_clicks(self, short_code: ShortCode) -> Link:
        """
        Increment click count for a given short code.

        Args:
            short_code: Short code of the link to increment.

        Returns:
            The updated Link entity.
        """
        ...

    @abstractmethod
    def increment_clicks_batch(self, short_codes: List[ShortCode]) -> None:
        """
        Bulk increment click counts for multiple short codes.

        Args:
            short_codes: List of short codes.
        """
        ...

    @abstractmethod
    def get_stats(self) -> dict:
        """
        Retrieve service statistics.

        Returns:
            Dictionary with keys:
                - ``'total_urls'``: total number of shortened URLs.
                - ``'total_clicks'``: sum of all clicks.
                - ``'popular_links'``: list of Link objects (most popular up to 10).
        """
        ...

    @abstractmethod
    def delete(self, short_code: ShortCode) -> bool:
        """
        Delete a link by its short code.

        Args:
            short_code: Short code of the link to delete.

        Returns:
            True if a link was deleted, False if no link with the given code existed.
        """
        ...

    @abstractmethod
    def get_recent(self, limit: int = 10) -> List[Link]:
        """
        Return most recently created links.

        Args:
            limit: Maximum number of links to return (default 10).

        Returns:
            List of Link objects ordered by creation date descending.
        """
        ...

    @abstractmethod
    def delete_unaccessed_before(self, cutoff: datetime) -> List[ShortCode]:
        """
        Delete links that haven't been accessed since the cutoff date.

        A link is considered "unaccessed" if its ``last_accessed`` timestamp is
        older than ``cutoff``, or if it has never been accessed (``last_accessed IS NULL``)
        and its ``created_at`` is older than ``cutoff``.

        Args:
            cutoff: Datetime (timezone-aware UTC) threshold.

        Returns:
            List of short codes that were deleted.
        """
        ...
    
    @abstractmethod
    def count_guest_links_by_identifier(self, identifier: str, since_days: int) -> int:
        """
        Count guest-created links for a given identifier within a time window.

        Args:
            identifier: Guest identifier (e.g. IP address).
            since_days: Number of days to look back.

        Returns:
            Number of links created by the guest in the last `since_days` days.
        """
        ...
    
    @abstractmethod
    def get_user_stats(self, user_id: str) -> dict:
        """
        Retrieve activity statistics for a specific user.

        Args:
            user_id: UUID of the user.

        Returns:
            Dictionary with keys:
                - ``'total_links'``: number of links owned by the user.
                - ``'total_clicks'``: total clicks across those links.
                - ``'recent_links'``: list of the user's 10 most recent Link objects.
        """
        ...

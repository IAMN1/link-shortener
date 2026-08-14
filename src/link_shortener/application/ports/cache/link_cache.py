from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from link_shortener.domain import DedupScope, Link, ShortCode, UrlHash


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
        ...

    @abstractmethod
    def get_by_hash(
        self, url_hash: UrlHash, scope: DedupScope
    ) -> Optional[Link]:
        """
        Retrieve a link by its URL hash within one deduplication scope.

        The scope is required because the entry answers "has this caller
        already shortened this URL", and one caller's answer is not another's.

        What comes back is a cached claim, not a verdict: it names a link
        that existed when it was written. Callers that are about to hand it
        to a client as an existing link must confirm it against the
        repository, which is the only place that knows whether the link is
        still there and still live.

        Args:
            url_hash (UrlHash): The URL hash value object.
            scope (DedupScope): The scope the lookup belongs to.

        Returns:
            Optional[Link]: Link if found, else None.
        """
        ...

    @abstractmethod
    def get_by_hashes(
        self, url_hashes: List[UrlHash], scope: DedupScope
    ) -> Dict[UrlHash, Optional[Link]]:
        """
        Bulk retrieve links by multiple URL hashes within one scope.

        Args:
            url_hashes (List[UrlHash]): List of URL hash value objects.
            scope (DedupScope): The scope the lookup belongs to.

        Returns:
            Dict[UrlHash, Optional[Link]]: Dictionary mapping each hash
                to either the found Link or None.
        """
        ...

    @abstractmethod
    def save(self, link: Link) -> None:
        """
        Store a single link in the cache.

        The implementation should store the link under appropriate keys
        (e.g., by short code and by hash) and set TTL.

        Args:
            link (Link): The Link to cache.
        """
        ...

    @abstractmethod
    def save_many(self, links: List[Link]) -> None:
        """
        Bulk store multiple links.

        Args:
            links (List[Link]): List of Link objects to cache.
        """
        ...

    @abstractmethod
    def delete_by_code(self, short_code: ShortCode) -> bool:
        """
        Remove what a code alone can name, for a link that is already gone.

        The entry filed under the URL hash cannot be named this way, and is
        left behind. That is the price of the only case this exists for: a
        row deleted while an entry describing it survived, where there is
        no entity left to name anything with. Without it, such an entry
        could not be cleared through the product at all -- every API
        surface would report the link deleted while the redirect went on
        serving it.

        Args:
            short_code: Code of the link that is no longer stored.

        Returns:
            ``True`` if the cache carried the deletion out.
        """
        ...

    @abstractmethod
    def delete(self, link: Link) -> bool:
        """
        Remove every entry written for a link, reporting whether it happened.

        The return value exists because this cache degrades by staying
        quiet, and quiet is the wrong answer here: a caller deleting rows
        needs to know that an entry describing a row that no longer exists
        is still there, and will be served for the rest of its TTL.

        The whole entity is required, not just its code, because the entry
        filed under the URL hash is keyed by hash *and* scope, and neither
        can be derived from a code. Reading the code entry to find the hash
        fails exactly when it matters: under ``allkeys-lru`` the two keys
        are evicted independently, so the code entry can be gone while the
        hash entry survives and keeps offering a deleted link.

        Args:
            link (Link): The link whose entries should go.

        Returns:
            ``True`` if the entries are gone (or were never there).
        """
        ...

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional

from link_shortener.domain.entities.link import Link
from link_shortener.domain.value_objects.dedup_scope import DedupScope
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.url_hash import UrlHash


class LinkRepository(ABC):
    """Interface for link storage operations."""

    @abstractmethod
    def save(self, link: Link) -> Link:
        """
        Insert a link, or update the stored one if it already exists.

        Identity is the link's own id: saving an entity that was read back
        from storage updates that row rather than inserting a second one.

        Args:
            link: Link entity to save.

        Returns:
            The saved Link (may include generated fields).
        """
        ...

    @abstractmethod
    def save_many(self, links: list[Link]) -> List[Link]:
        """
        Bulk insert links.

        Unlike ``save``, this is an insert path only: it serves batch
        creation, where every link is new by construction. Passing an
        already-stored entity is a programming error, not an update.

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
    def find_live_by_hash(
        self, url_hash: UrlHash, scope: DedupScope
    ) -> Optional[Link]:
        """
        Find the link a URL deduplicates against, within one scope.

        Both restrictions are part of the answer, not optional filters:

        - **Scope.** Matching on the hash alone returned links belonging to
          other callers, who then "created" a link they did not own.
        - **Liveness.** An expired link must not be handed out as an existing
          one. It answers ``410`` at redirect time, so returning it made the
          URL permanently unshortenable for that scope.

        When several live links match -- possible, since nothing stops two
        concurrent creations -- the oldest is returned, so that every caller
        converges on the same one.

        Args:
            url_hash: URL hash value object.
            scope: The scope to deduplicate within.

        Returns:
            The live link for this hash in this scope, else None.
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
    def find_live_by_hashes(
        self, url_hashes: List[UrlHash], scope: DedupScope
    ) -> Dict[UrlHash, Optional[Link]]:
        """
        Bulk form of ``find_live_by_hash``, with the same two restrictions.

        Args:
            url_hashes: List of URL hash value objects.
            scope: The scope to deduplicate within.

        Returns:
            Dictionary mapping each requested hash to its live link in this
            scope, or None.
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
    def delete(self, link_id: str) -> bool:
        """
        Delete a link by its identifier.

        By identifier and not by short code, because the caller has already
        decided something about a particular row -- whether it may be
        deleted at all -- and naming the row a second time by a lookup key
        invites the answer to be a different row than the one that was
        judged. Short codes are unique but not eternal: one can be freed by
        a delete and taken by a later link.

        Args:
            link_id: Identifier of the link to delete.

        Returns:
            True if a link was deleted, False if no link with that id existed.
        """
        ...

    @abstractmethod
    def delete_by_owner(self, user_id: str) -> List[Link]:
        """
        Delete every link belonging to one account.

        The deleted entities are returned rather than a count, because the
        caller has caches to clear and only an entity names every key a link
        was written under: the deduplication entry is keyed by hash and
        scope, and neither can be derived from a short code.

        Args:
            user_id: Identifier of the owning account.

        Returns:
            The deleted Link entities.
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
    def delete_expired(self, now: datetime) -> List[Link]:
        """
        Delete links whose expiry has passed.

        Only ``expires_at`` decides. Neither the owner nor the time since the
        last click may enter into it: a link nobody has clicked is still a
        link its owner made, while an expired one already answers ``410``, so
        deleting it removes nothing that was still being served.

        The deleted entities are returned rather than their codes because
        invalidating the cache needs more than a code -- the entry filed
        under the URL hash is keyed by hash and scope, and a code alone
        cannot name it.

        Args:
            now: Timezone-aware UTC instant to judge expiry against.

        Returns:
            The links that were deleted.
        """
        ...
    
    @abstractmethod
    def lock_guest_quota(self, identifier: str) -> None:
        """
        Serialise link creation for one guest identifier.

        Counting links and then inserting one is two statements, and nothing
        ties them together: concurrent requests from the same caller each
        read the same allowance and each spend it in full. Measured at a
        full quota per concurrent request -- five simultaneous batches
        produced fifty links against a limit of ten, and the links stay.

        Callers must take this inside the very transaction that both counts
        and inserts, before the count. It is released when that transaction
        ends, whichever way it ends.

        The lock is per identifier: two different guests never wait on each
        other, and one guest's own requests are exactly what needs ordering.

        Implementations on engines without such a lock are expected to do
        nothing and to say so -- the quota is then advisory there.

        Args:
            identifier: Guest identifier the quota is counted under.
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

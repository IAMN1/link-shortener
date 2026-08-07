from typing import Dict, List, Tuple

from link_shortener.application.dtos.batch import BatchItemResponse
from link_shortener.domain import DedupScope, Link, LinkRepository
from link_shortener.application.ports.cache.link_cache import LinkCache


class BatchLinkFetcher:
    """
    Fetches links for a set of URL groups, checking cache then repository.

    Returns three collections:
        - Results for items already found.
        - Groups that still need link creation.
        - Links that were fetched from DB and should be cached.
    """

    def __init__(self, cache: LinkCache):
        """
        Args:
            cache: Link cache (L2) implementation.
        """
        self.cache = cache
    
    def fetch(
        self,
        repository: LinkRepository,
        groups: List[Dict],
        base_url: str,
        scope: DedupScope,
    ) -> Tuple[List[BatchItemResponse], List[Dict], List[Link]]:
        """
        Look up existing links for each group, within one scope.

        Steps:
            1. Bulk cache lookup by hash.
            2. For cache misses, bulk DB lookup by hash.
            3. Build BatchItemResponse for found items and identify missing groups.

        Both lookups are restricted to the caller's own live links, for the
        same reasons the single-link path is: a match on the URL alone hands
        back somebody else's link, and an expired match hands back a code
        that answers ``410``.

        Args:
            repository: Link repository for DB queries.
            groups: List of valid group dicts (must contain ``hash``, ``original_url``,
                ``urls``).
            base_url: Base URL for constructing short URLs.
            scope: The scope to deduplicate within.

        Returns:
            Tuple of:
                - ``results``: list of BatchItemResponse for found items.
                - ``groups_to_create``: list of groups that need new links.
                - ``links_to_cache``: list of Link objects (from DB) to be cached.
        """
        if not groups:
            return [], [], []

        # ---- 1. Cache lookup ----
        hashes = [g["hash"] for g in groups]
        cached_map = self.cache.get_by_hashes(hashes, scope)

        confirmed = self._confirm(cached_map, repository, scope)

        cache_results = []
        groups_not_in_cache = []

        for group in groups:
            link = confirmed.get(group["hash"])
            if link:
                for url in group["urls"]:
                    cache_results.append(
                        BatchItemResponse.success_(
                            url=url,
                            short_code=link.short_code.value,
                            original_url=link.original_url.value,
                            base_url=base_url,
                            clicks=link.clicks,
                            from_cache=True,
                            expires_at=link.expires_at,
                        )
                    )
            else:
                groups_not_in_cache.append(group)
        
        if not groups_not_in_cache:
            return cache_results, [], []
        
        # ---- 2. Database lookup for missing ----
        missing_hashes = [g["hash"] for g in groups_not_in_cache]
        db_map = repository.find_live_by_hashes(missing_hashes, scope)

        db_results = []
        groups_to_create = []
        links_to_cache = []

        for group in groups_not_in_cache:
            link = db_map.get(group["hash"])
            if link:
                for url in group["urls"]:
                    db_results.append(
                        BatchItemResponse.success_(
                            url=url,
                            short_code=link.short_code.value,
                            original_url=link.original_url.value,
                            base_url=base_url,
                            clicks=link.clicks,
                            is_new=False,
                            expires_at=link.expires_at,
                        )
                    )
                links_to_cache.append(link)
            else:
                groups_to_create.append(group)

        all_results = cache_results + db_results
        return all_results, groups_to_create, links_to_cache

    def _confirm(
        self,
        cached_map: Dict,
        repository: LinkRepository,
        scope: DedupScope,
    ) -> Dict:
        """
        Keep only the cached hits the repository still stands behind.

        A cached entry names a link that existed when it was written. Serving
        it unchecked returns codes for links that have since been deleted or
        expired, and under ``allkeys-lru`` an entry can easily outlive the
        row it describes. Entries that fail the check are dropped, so the
        next batch does not repeat the round trip.

        Verification is one bulk lookup for the whole batch, not one per
        item.

        Args:
            cached_map: Hash to cached link, as returned by the cache.
            repository: Link repository.
            scope: Scope the lookup was made in.

        Returns:
            Hash to confirmed link, taken from the repository.
        """
        candidates = {h: link for h, link in cached_map.items() if link}
        if not candidates:
            return {}

        stored = repository.find_by_codes(
            [link.short_code for link in candidates.values()]
        )

        confirmed = {}
        for url_hash, cached_link in candidates.items():
            link = stored.get(cached_link.short_code)
            if (
                link is not None
                and link.url_hash == url_hash
                and link.dedup_scope() == scope
                and not link.is_expired()
            ):
                confirmed[url_hash] = link
            else:
                self.cache.delete(cached_link)
        return confirmed

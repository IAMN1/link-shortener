from typing import Dict, List, Tuple

from link_shortener.application.dtos.batch import BatchItemResponse
from link_shortener.domain import Link, LinkRepository
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
    
    def fetch(self, repository: LinkRepository, groups: List[Dict], base_url: str) -> Tuple[List[BatchItemResponse], List[Dict], List[Link]]:
        """
        Look up existing links for each group.

        Steps:
            1. Bulk cache lookup by hash.
            2. For cache misses, bulk DB lookup by hash.
            3. Build BatchItemResponse for found items and identify missing groups.

        Args:
            repository: Link repository for DB queries.
            groups: List of valid group dicts (must contain ``hash``, ``original_url``,
                ``urls``).
            base_url: Base URL for constructing short URLs.

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
        cached_map = self.cache.get_by_hashes(hashes)

        cache_results = []
        groups_not_in_cache = []

        for group in groups:
            link = cached_map.get(group["hash"])
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
                        )
                    )
            else:
                groups_not_in_cache.append(group)
        
        if not groups_not_in_cache:
            return cache_results, [], []
        
        # ---- 2. Database lookup for missing ----
        missing_hashes = [g["hash"] for g in groups_not_in_cache]
        db_map = repository.find_by_hashes(missing_hashes)

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
                        )
                    )
                links_to_cache.append(link)
            else:
                groups_to_create.append(group)

        all_results = cache_results + db_results
        return all_results, groups_to_create, links_to_cache

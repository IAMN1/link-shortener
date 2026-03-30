from typing import Dict, List, Tuple

from link_shortener.domain import Link, LinkRepository
from link_shortener.application.dtos.responses import BatchItemResponse
from link_shortener.application.ports.cache.link_cache import LinkCache


class BatchLinkFetcher:
    """
    Fetches existing links from cache and database in batch.

    This class is responsible for:
        - Checking the cache for each group's hash.
        - For cache misses, querying the repository.
        - Returning results, groups that need creation, and links to be cached.
    """

    def __init__(self, cache: LinkCache, repository: LinkRepository):
        """
        Initialize the fetcher.

        Args:
            cache: Link cache implementation.
            repository: Link repository.
        """
        self.cache = cache
        self.repository = repository
    
    def fetch(self, groups: List[Dict], base_url: str) -> Tuple[List[BatchItemResponse], List[Dict], List[Link]]:
        """
        Fetch existing links for the given groups.

        Args:
            groups: List of valid group dictionaries (each with 'hash', 'original_url', 'urls').
            base_url: Base URL of the service for building short URLs.

        Returns:
            A tuple containing:
                - results: BatchItemResponse objects for groups found in cache or DB.
                - groups_to_create: List of groups that need new link creation.
                - links_to_cache: List of Link objects that were found in DB and should be cached.
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
        db_map = self.repository.find_by_hashes(missing_hashes)

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
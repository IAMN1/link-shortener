from typing import Dict, List, Optional
from link_shortener.application import LinkCache, StatsCache, RedirectCache
from link_shortener.domain import Link, ShortCode, UrlHash


class NullCache(LinkCache, RedirectCache, StatsCache):
    """
    Null-object implementation for cache.
    """

    def get_by_code(self, short_code: ShortCode) -> Optional[Link]:
        return None

    def get_by_hash(self, url_hash: UrlHash) -> Optional[Link]:
        return None

    def get_by_hashes(self, url_hashes: List[UrlHash]) -> Dict[UrlHash, Optional[Link]]:
        return {h: None for h in url_hashes}

    def save(self, link: Link) -> None:
        pass

    def save_many(self, links: List[Link]) -> None:
        pass

    def delete(self, short_code: ShortCode) -> None:
        pass

    # RedirectCache methods
    def get_original_url(self, short_code: ShortCode) -> Optional[str]:
        return None

    def save_original_url(self, short_code: ShortCode, original_url: str) -> None:
        pass

    # StatsCache methods
    def get_stats(self) -> Optional[dict]:
        return None

    def save_stats(self, stats: dict) -> None:
        pass

    def delete_stats(self) -> None:
        pass
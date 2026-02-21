from typing import Dict, List, Optional

from link_shortener.application.ports.cache.link_cache import LinkCache
from link_shortener.application.ports.cache.link_service_stats_cache import StatsCache
from link_shortener.application.ports.cache.redirect_cache import RedirectCache
from link_shortener.domain import Link, ShortCode, UrlHash


class NullCache(LinkCache, RedirectCache, StatsCache):
    """
    Null-object implementation of all cache interfaces.

    All methods do nothing and return None or empty results.
    Used when caching is disabled or unavailable.
    """

    def get_by_code(self, short_code: ShortCode) -> Optional[Link]:
        """No-op: always return None."""
        return None

    def get_by_hash(self, url_hash: UrlHash) -> Optional[Link]:
        """No-op: always return None."""
        return None

    def get_by_hashes(self, url_hashes: List[UrlHash]) -> Dict[UrlHash, Optional[Link]]:
        """No-op: return dict with all None values."""
        return {h: None for h in url_hashes}

    def save(self, link: Link) -> None:
        """No-op: do nothing."""
        pass

    def save_many(self, links: List[Link]) -> None:
        """No-op: do nothing."""
        pass

    def delete(self, short_code: ShortCode) -> None:
        """No-op: do nothing."""
        pass

    # ========== RedirectCache methods ==========
    def get_original_url(self, short_code: ShortCode) -> Optional[str]:
        """No-op: always return None."""
        return None

    def save_original_url(self, short_code: ShortCode, original_url: str) -> None:
        """No-op: do nothing."""
        pass

    # ========== StatsCache methods ==========
    def get_stats(self) -> Optional[dict]:
        """No-op: always return None."""
        return None

    def save_stats(self, stats: dict) -> None:
        """No-op: do nothing."""
        pass

    def delete_stats(self) -> None:
        """No-op: do nothing."""
        pass
from datetime import datetime
from typing import Dict, List, Optional

from link_shortener.application.ports.cache.cache_health import CacheHealth
from link_shortener.application.ports.cache.link_cache import LinkCache
from link_shortener.application.ports.cache.link_service_stats_cache import StatsCache
from link_shortener.application.ports.cache.redirect_cache import (
    CachedRedirect, RedirectCache
)
from link_shortener.domain import DedupScope, Link, ShortCode, UrlHash


class NullCache(LinkCache, RedirectCache, StatsCache, CacheHealth):
    """
    Null-object cache that discards all data.

    Used when caching is disabled or as a safe fallback.
    All methods are no-ops and return ``None`` or empty results.
    """

    cache_type = "Null"

    # ========== CacheHealth methods ==========
    def is_configured(self) -> bool:
        """No backend is involved; there is nothing to be up or down."""
        return False

    def ping(self) -> bool:
        """A cache with nothing to connect to cannot be unreachable."""
        return True

    # ========== Link Cache methods ==========
    def get_by_code(self, short_code: ShortCode) -> Optional[Link]:
        """No-op: always return None."""
        return None

    def get_by_hash(
        self, url_hash: UrlHash, scope: DedupScope
    ) -> Optional[Link]:
        """No-op: always return None."""
        return None

    def get_by_hashes(
        self, url_hashes: List[UrlHash], scope: DedupScope
    ) -> Dict[UrlHash, Optional[Link]]:
        """No-op: return dict with all None values."""
        return {h: None for h in url_hashes}

    def save(self, link: Link) -> None:
        """No-op: do nothing."""
        pass

    def save_many(self, links: List[Link]) -> None:
        """No-op: do nothing."""
        pass

    def delete(self, link: Link) -> bool:
        """No-op: a cache that stores nothing has nothing left behind."""
        return True

    def delete_by_code(self, short_code: ShortCode) -> bool:
        """No-op: a cache that stores nothing has nothing left behind."""
        return True

    def delete_redirect(self, short_code: ShortCode) -> None:
        """No-op: do nothing."""
        pass

    # ========== RedirectCache methods ==========
    def get_redirect(self, short_code: ShortCode) -> Optional[CachedRedirect]:
        """No-op: always return None."""
        return None

    def save_redirect(
        self,
        short_code: ShortCode,
        original_url: str,
        expires_at: Optional[datetime] = None,
    ) -> None:
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

    def close(self) -> None:
        """No-op: nothing to close."""
        pass

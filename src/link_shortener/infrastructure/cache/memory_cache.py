import time
from threading import RLock
from typing import Any, Dict, List, Optional

from link_shortener.application import LinkCache, RedirectCache, StatsCache
from link_shortener.domain import Link, ShortCode, UrlHash
from link_shortener.infrastructure.cache.cache_key_generator import (
    CacheKeyGenerator
)


class InMemoryLinkCache(LinkCache, RedirectCache, StatsCache):
    """
    In-memory cache implementation with TTL support.

    This cache stores data in Python dictionaries and uses a simple
    expiration mechanism based on timestamps. Suitable for development,
    testing, or when Redis is not available. All operations are thread-safe
    using RLock.

    Implements all three cache interfaces: LinkCache, RedirectCache, StatsCache.
    """

    def __init__(
        self, prefix: str, link_ttl: int = 30, stats_ttl: int = 3
    ):
        """
        Initialize the in-memory cache.

        Args:
            prefix: Prefix for cache keys (used by CacheKeyGenerator).
            link_ttl: Time-to-live in seconds for link entries.
            stats_ttl: Time-to-live in seconds for stats entries.
        """
        self.key_gen = CacheKeyGenerator(prefix=prefix)

        # Хранилища
        self._links: Dict[str, Link] = {}  # code -> link
        self._redirects: Dict[str, str] = {}  # code -> original_url
        self._stats: Optional[Dict[str, Any]] = None

        # TTL
        self._expiry: Dict[str, float] = {}
        self.link_ttl = link_ttl
        self.stats_ttl = stats_ttl

        self._lock = RLock()

    def _is_expired(self, key: str) -> bool:
        """Check if a key has exceeded its TTL."""
        if key not in self._expiry:
            return False
        return time.time() > self._expiry[key]

    def _clean_expired(self, key_type: Optional[str] = None):
        """
        Remove expired keys from all stores.

        If key_type is provided (e.g., "code", "hash", "redirect", "stats"),
        only clean keys of that type (by key prefix). Otherwise, clean all.
        """
        current_time = time.time()
        expired_keys = [
            key for key, expiry in self._expiry.items() if expiry < current_time
        ]

        for key in expired_keys:
            # Очистка хранилищ редиректа и ссылок
            if key_type is None or key.startswith(f"{self.key_gen.prefix}:{key_type}"):

                if key in self._links:
                    del self._links[key]
                if key in self._redirects:
                    del self._redirects[key]

                del self._expiry[key]

            # Очистка статистики
            stats_key = self.key_gen.for_stats()
            if stats_key in self._expiry and self._expiry[stats_key] < current_time:
                self._stats = None
                del self._expiry[stats_key]

    def clear_all(self) -> None:
        """Clear all cached data (for testing purposes)."""
        with self._lock:
            self._links.clear()
            self._redirects.clear()
            self._stats = None
            self._expiry.clear()

    def get_cache_info(self) -> Dict[str, Any]:
        """
        Return information about current cache state 
        (for monitoring/debugging).
        """
        with self._lock:
            self._clean_expired()

            return {
                "link_count": len(self._links),
                "redirect_count": len(self._redirects),
                "has_stats": self._stats is not None,
                "total_keys": len(self._expiry),
            }

    # ========== LinkCache методы ==========
    def get_by_code(self, short_code: ShortCode) -> Optional[Link]:
        with self._lock:
            self._clean_expired("code")
            key = self.key_gen.for_short_code(short_code.value)
            return self._links.get(key)

    def get_by_hash(self, url_hash: UrlHash) -> Optional[Link]:
        with self._lock:
            self._clean_expired("hash")
            key = self.key_gen.for_url_hash(url_hash.value)
            return self._links.get(key)

    def get_by_hashes(self, url_hashes: List[UrlHash]) -> Dict[UrlHash, Optional[Link]]:
        with self._lock:
            self._clean_expired("hash")

            result = {}
            for url_hash in url_hashes:
                key = self.key_gen.for_url_hash(url_hash.value)
                result[url_hash] = self._links.get(key)
            return result

    def save(self, link: Link) -> None:
        """Store a link under multiple keys (hash, code, and redirect)."""
        with self._lock:
            hash_key = self.key_gen.for_url_hash(link.url_hash.value)
            code_key = self.key_gen.for_short_code(link.short_code.value)
            redirect_key = self.key_gen.for_redirect(link.short_code.value)

            self._links[hash_key] = link
            self._links[code_key] = link
            self._redirects[redirect_key] = link.original_url.value

            # Устанавливаем TTL
            current_time = time.time()
            self._expiry[hash_key] = current_time + self.link_ttl
            self._expiry[code_key] = current_time + self.link_ttl
            self._expiry[redirect_key] = current_time + self.link_ttl

    def save_many(self, links: List[Link]) -> None:
        with self._lock:
            for link in links:
                self.save(link)

    def delete(self, short_code: ShortCode) -> None:
        """
        Delete all data associated with a short code 
        (hash, code, redirect keys).
        """
        with self._lock:
            # Удаление данных ссылки из кэша
            key_code = self.key_gen.for_short_code(short_code.value)
            key_redirect = self.key_gen.for_redirect(short_code.value)

            if key_redirect in self._redirects:
                del self._redirects[key_redirect]
            if key_redirect in self._expiry:
                del self._expiry[key_redirect]

            if key_code in self._links:
                link = self._links[key_code]
                key_hash = self.key_gen.for_url_hash(link.url_hash.value)

                if key_hash in self._links:
                    del self._links[key_hash]
                del self._links[key_code]

                for key in [key_code, key_hash, key_redirect]:
                    if key in self._expiry:
                        del self._expiry[key]

    # ========== RedirectCache методы ==========
    def get_original_url(self, short_code: ShortCode) -> Optional[str]:

        with self._lock:
            self._clean_expired("redirect")
            key = self.key_gen.for_redirect(short_code.value)
            return self._redirects.get(key)

    def save_original_url(self, short_code: ShortCode, original_url: str) -> None:
        key = self.key_gen.for_redirect(short_code.value)
        self._redirects[key] = original_url
        self._expiry[key] = time.time() + self.link_ttl

    # ========== StatsCache методы ==========
    def get_stats(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._clean_expired("stats")
            key = self.key_gen.for_stats()
            if self._stats and not self._is_expired(key):
                return self._stats
            return None

    def save_stats(self, stats: Dict[str, Any]) -> None:
        with self._lock:
            self._stats = stats
            key = self.key_gen.for_stats()
            self._expiry[key] = time.time() + self.stats_ttl

    def delete_stats(self) -> None:
        with self._lock:
            self._stats = None
            key = self.key_gen.for_stats()
            if key in self._expiry:
                del self._expiry[key]

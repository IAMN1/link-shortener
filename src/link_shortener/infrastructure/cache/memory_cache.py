"""
Thread-safe in-memory cache with TTL support.

Implements LinkCache, RedirectCache, and StatsCache using Python dictionaries.
Suitable for development and testing when Redis is unavailable.
"""

import time
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Dict, List, Optional

from link_shortener.application import (
    CachedRedirect, CacheHealth, LinkCache, RedirectCache, StatsCache,
    CacheKeyBuilder
)
from link_shortener.domain import DedupScope, Link, ShortCode, UrlHash



class InMemoryLinkCache(LinkCache, RedirectCache, StatsCache, CacheHealth):
    """
    In-memory cache that stores data in Python dictionaries.

    All operations are protected by a reentrant lock for thread safety.
    Expired entries are cleaned lazily on reads.
    """

    cache_type = "InMemory"

    def __init__(self, prefix: str, link_ttl: int, stats_ttl: int):
        """
        Args:
            prefix: Prefix used by CacheKeyBuilder to namespace keys.
            link_ttl: Time-to-live in seconds for link entries.
            stats_ttl: Time-to-live in seconds for statistics.
        """
        self.key_gen = CacheKeyBuilder(prefix=prefix)

        # Internal storage
        self._links: Dict[str, Link] = {}               # key -> Link object
        self._redirects: Dict[str, CachedRedirect] = {}  # key -> cached redirect
        self._stats: Optional[Dict[str, Any]] = None

        # Expiry timestamps: key -> expiration time (monotonic seconds)
        self._expiry: Dict[str, float] = {}
        self.link_ttl = link_ttl
        self.stats_ttl = stats_ttl

        self._lock = RLock()

    # ========== CacheHealth methods ==========
    def is_configured(self) -> bool:
        """No backend is involved; there is nothing to be up or down."""
        return False

    def ping(self) -> bool:
        """A cache with nothing to connect to cannot be unreachable."""
        return True

    def _is_expired(self, key: str) -> bool:
        """
        Return True if the key's TTL has expired.

        Args:
            key: Cache key.

        Returns:
            True if expired or absent.
        """
        if key not in self._expiry:
            return False
        return time.time() > self._expiry[key]

    def _clean_expired(self):
        """
        Remove expired entries from all stores.

        This method iterates over all keys and deletes those whose
        expiration timestamp is in the past. It also handles the
        special case of the stats entry which is stored separately.
        """
        current_time = time.time()
        expired_keys = [
            key for key, expiry in self._expiry.items() if expiry < current_time
        ]

        for key in expired_keys:
            # Remove from all relevant dictionaries
            if key in self._links:
                del self._links[key]
            if key in self._redirects:
                del self._redirects[key]
            del self._expiry[key]

        # Also check stats separately (stored in self._stats, not in _links)
        stats_key = self.key_gen.for_stats()
        if stats_key in self._expiry and self._expiry[stats_key] < current_time:
            self._stats = None
            del self._expiry[stats_key]

    def clear_all(self) -> None:
        """Clear all cached data (intended for testing)."""
        with self._lock:
            self._links.clear()
            self._redirects.clear()
            self._stats = None
            self._expiry.clear()

    def get_cache_info(self) -> Dict[str, Any]:
        """
        Return monitoring information about the cache state.

        Returns:
            Dict with link_count, redirect_count, has_stats, total_keys.
        """
        with self._lock:
            self._clean_expired()

            return {
                "link_count": len(self._links),
                "redirect_count": len(self._redirects),
                "has_stats": self._stats is not None,
                "total_keys": len(self._expiry),
            }

    # ========== LinkCache methods ==========
    def get_by_code(self, short_code: ShortCode) -> Optional[Link]:
        """Retrieve a link by its short code."""

        with self._lock:
            self._clean_expired()
            key = self.key_gen.for_short_code(short_code.value)
            return self._links.get(key)

    def get_by_hash(
        self, url_hash: UrlHash, scope: DedupScope
    ) -> Optional[Link]:
        """Retrieve a link by its URL hash within one deduplication scope."""

        with self._lock:
            self._clean_expired()
            key = self.key_gen.for_url_hash(url_hash.value, scope.token())
            return self._links.get(key)

    def get_by_hashes(
        self, url_hashes: List[UrlHash], scope: DedupScope
    ) -> Dict[UrlHash, Optional[Link]]:
        """
        Retrieve multiple links by their URL hashes within one scope.

        Returns a dictionary mapping each input hash to either the found Link or None.
        """

        with self._lock:
            self._clean_expired()

            token = scope.token()
            result = {}
            for url_hash in url_hashes:
                key = self.key_gen.for_url_hash(url_hash.value, token)
                result[url_hash] = self._links.get(key)
            return result

    def save(self, link: Link) -> None:
        """Store a link under multiple keys (hash, code, and redirect) with TTL."""
        with self._lock:
            hash_key = self.key_gen.for_url_hash(
                link.url_hash.value, link.dedup_scope().token()
            )
            code_key = self.key_gen.for_short_code(link.short_code.value)
            redirect_key = self.key_gen.for_redirect(link.short_code.value)

            self._links[hash_key] = link
            self._links[code_key] = link

            # Set expiration timestamps
            current_time = time.time()
            self._expiry[hash_key] = current_time + self.link_ttl
            self._expiry[code_key] = current_time + self.link_ttl

            # The redirect entry goes through the same rules as
            # save_redirect: it carries the expiry and never outlives the
            # link. Storing a bare URL on the full cache TTL is how an
            # expired link kept being served from L1.
            redirect_ttl = self._redirect_ttl(link.expires_at)
            if redirect_ttl is None:
                self._redirects.pop(redirect_key, None)
                self._expiry.pop(redirect_key, None)
            else:
                self._redirects[redirect_key] = CachedRedirect(
                    short_code=link.short_code.value,
                    original_url=link.original_url.value,
                    expires_at=link.expires_at,
                )
                self._expiry[redirect_key] = current_time + redirect_ttl

    def save_many(self, links: List[Link]) -> None:
        """Bulk store multiple links."""
        with self._lock:
            for link in links:
                self.save(link)

    def delete_by_code(self, short_code: ShortCode) -> bool:
        """
        Remove the two entries a code can name, for a link already gone.

        Returns:
            ``True`` -- an in-process dictionary cannot fail to forget.
        """
        with self._lock:
            keys = [
                self.key_gen.for_short_code(short_code.value),
                self.key_gen.for_redirect(short_code.value),
            ]
            for key in keys:
                self._links.pop(key, None)
                self._redirects.pop(key, None)
                self._expiry.pop(key, None)
            return True

    def delete(self, link: Link) -> bool:
        """
        Remove every entry written for a link (hash, code, redirect keys).

        Keys are named from the entity rather than discovered by reading the
        code entry first: that entry may already be gone, and the hash entry
        left behind then keeps answering deduplication lookups.

        Returns:
            ``True`` -- an in-process dictionary cannot fail to forget.
        """
        with self._lock:
            keys = [
                self.key_gen.for_short_code(link.short_code.value),
                self.key_gen.for_redirect(link.short_code.value),
                self.key_gen.for_url_hash(
                    link.url_hash.value, link.dedup_scope().token()
                ),
            ]
            for key in keys:
                self._links.pop(key, None)
                self._redirects.pop(key, None)
                self._expiry.pop(key, None)
            return True

    def delete_redirect(self, short_code: ShortCode) -> None:
        """Remove only the redirect entry for a short code."""
        with self._lock:
            key = self.key_gen.for_redirect(short_code.value)
            self._redirects.pop(key, None)
            self._expiry.pop(key, None)

    # ========== RedirectCache methods ==========
    def _redirect_ttl(self, expires_at: Optional[datetime]) -> Optional[float]:
        """
        Work out how long a redirect entry may live.

        Capped at the link's own remaining lifetime, so the entry cannot
        outlive what it points at.

        Args:
            expires_at: When the link expires, or ``None`` if never.

        Returns:
            TTL in seconds, or ``None`` if the link has already expired.
        """
        if expires_at is None:
            return self.link_ttl

        remaining = (expires_at - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            return None

        return min(self.link_ttl, remaining)

    def get_redirect(self, short_code: ShortCode) -> Optional[CachedRedirect]:
        """Retrieve the cached redirect for a short code (L1)."""

        with self._lock:
            self._clean_expired()
            key = self.key_gen.for_redirect(short_code.value)
            entry = self._redirects.get(key)

        if entry is None:
            return None

        # Same rules as the Redis implementation: an entry that cannot
        # vouch for itself is a miss, not an answer.
        if not entry.is_for(short_code) or entry.is_expired():
            return None

        return entry

    def save_redirect(
        self,
        short_code: ShortCode,
        original_url: str,
        expires_at: Optional[datetime] = None,
    ) -> None:
        """Store a redirect entry, capped at the link's own lifetime."""
        ttl = self._redirect_ttl(expires_at)
        if ttl is None:
            return

        with self._lock:
            key = self.key_gen.for_redirect(short_code.value)
            self._redirects[key] = CachedRedirect(
                short_code=short_code.value,
                original_url=original_url,
                expires_at=expires_at,
            )
            self._expiry[key] = time.time() + ttl

    # ========== StatsCache methods ==========
    def get_stats(self) -> Optional[Dict[str, Any]]:
        """Retrieve cached service statistics."""

        with self._lock:
            self._clean_expired()
            key = self.key_gen.for_stats()
            # Return cached data if the key exists and has not expired.
            if key in self._expiry and not self._is_expired(key):
                return self._stats
            # Otherwise invalidate and return None.
            self._stats = None
            return None

    def save_stats(self, stats: Dict[str, Any]) -> None:
        """Cache service statistics with TTL."""

        with self._lock:
            self._stats = stats
            key = self.key_gen.for_stats()
            self._expiry[key] = time.time() + self.stats_ttl

    def delete_stats(self) -> None:
        """Invalidate cached statistics."""

        with self._lock:
            self._stats = None
            key = self.key_gen.for_stats()
            if key in self._expiry:
                del self._expiry[key]

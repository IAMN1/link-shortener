class CacheKeyBuilder:
    """
    Generates consistent cache keys using a configurable prefix.

    Pure logic; no persistence dependency.
    """
    def __init__(self, prefix: str):
        self.prefix = prefix
    
    def _build_key(self, *parts: str) -> str:
        """
        Join prefix and parts with colon as separator.

        Args:
            *parts: Key segments.

        Returns:
            Full cache key string.
        """
        return ":".join([self.prefix] + list(parts))
    
    def for_redirect(self, short_code: str) -> str:
        """
        Build key for L1 redirect cache.

        Args:
            short_code: Short code string.

        Returns:
            Key string.
        """
        return self._build_key("redirect", short_code)
    
    def for_short_code(self, short_code: str) -> str:
        """
        Build key for Link by short code.

        Args:
            short_code: Short code string.

        Returns:
            Key string.
        """
        return self._build_key("code", short_code)
    
    def for_url_hash(self, url_hash: str, scope: str) -> str:
        """
        Build key for Link by URL hash within one deduplication scope.

        The scope is part of the key because the entry answers the question
        "has *this caller* already shortened this URL". A key without it let
        one caller's entry answer for another.

        Args:
            url_hash: 64-char hex hash.
            scope: Scope token from ``DedupScope.token()``.

        Returns:
            Key string.
        """
        return self._build_key("hash", scope, url_hash)
    
    def for_stats(self) -> str:
        """
        Build key for global service statistics.

        Returns:
            Key string.
        """
        return self._build_key("stats", "global")

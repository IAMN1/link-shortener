class CacheKeyGenerator:
    """
    Generates consistent cache keys with a common prefix.

    This class centralizes key generation logic to avoid duplication
    and ensure all cache keys follow the same pattern.
    """

    def __init__(self, prefix: str = "link_shortener"):
        """
        Initialize the key generator.

        Args:
            prefix (str, optional): Common prefix for all keys. 
                Defaults to "link_shortener".
        """
        self.prefix = prefix

    def _build_key(self, *parts: str) -> str:
        """
        Build a colon-separated key with the prefix.

        Args:
            *parts: Variable number of key parts.

        Returns:
            A string key like "prefix:part1:part2".
        """
        return ":".join([self.prefix] + list(parts))

    def for_redirect(self, short_code: str) -> str:
        """
        Generate key for fast redirect cache (L1).

        Args:
            short_code: Short code string.

        Returns:
            Cache key for redirect mapping.
        """
        return self._build_key("redirect", short_code)

    def for_short_code(self, short_code: str) -> str:
        """
        Generate key for full link cache by short code (L2).

        Args:
            short_code: Short code string.

        Returns:
            Cache key for link by short code.
        """
        return self._build_key("code", short_code)

    def for_url_hash(self, url_hash: str) -> str:
        """
        Generate key for deduplication cache by URL hash.

        Args:
            url_hash: URL hash string (64 hex chars).

        Returns:
            Cache key for link by URL hash.
        """
        return self._build_key("hash", url_hash)

    def for_stats(self) -> str:
        """Generate key for global service statistics cache.

        Returns:
            Cache key for stats."""
        return self._build_key("stats", "global")

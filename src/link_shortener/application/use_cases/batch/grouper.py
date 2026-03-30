from typing import Dict, List
from urllib.parse import urlparse

from link_shortener.domain import ShorteningPolicy, OriginalUrl
from link_shortener.application.ports.logger.logger import Logger


class UrlGrouper:
    """
    Groups URLs by their hash for deduplication.

    Valid URLs are grouped under their hash; invalid URLs are grouped
    under separate keys with a flag indicating the error.
    """
    def __init__(self, allowed_schemes: List[str], logger: Logger):
        """
        Initialize the grouper.

        Args:
            allowed_schemes: List of allowed URL schemes (e.g., ['http', 'https']).
            logger: Logger for logging invalid URLs.
        """
        self.allowed_schemes = allowed_schemes
        self.logger = logger
    
    def group(self, urls: List[str], policy: ShorteningPolicy) -> Dict[str, Dict]:
        """
        Group URLs by hash.

        Args:
            urls: List of URL strings.
            policy: Shortening policy used to compute hashes.

        Returns:
            A dictionary where:
                - Key: hash string (for valid URLs) or "invalid_{counter}" (for invalid).
                - Value: dict with fields:
                    - hash: UrlHash (if valid)
                    - original_url: OriginalUrl (if valid)
                    - urls: list of input strings for this group
                    - is_valid: bool
                    - error: error message (if invalid)
        """

        groups = {}
        invalid_counter = 0

        for url in urls:
            try:
                self._validate_scheme(url)
                original_url = OriginalUrl(url)
                url_hash = policy.calculate_hash(original_url)
                key = url_hash.value

                if key not in groups:
                    groups[key] = {
                        "hash": url_hash,
                        "original_url": original_url,
                        "urls": [],
                        "is_valid": True,
                    }
                groups[key]["urls"].append(url)
            except ValueError as e:
                key = f"invalid_{invalid_counter}"
                invalid_counter += 1
                groups[key] = {
                    "hash": None,
                    "original_url": None,
                    "urls": [url],
                    "is_valid": False,
                    "error": str(e),
                }
                self.logger.warning("Invalid URL in batch", url=url[:50], error=str(e))
        return groups
    
    def _validate_scheme(self, url: str) -> None:
        """
        Validate the URL scheme against the allowed list.

        Args:
            url: URL string.

        Raises:
            ValueError: If the scheme is not allowed.
        """
        parsed = urlparse(url)
        if parsed.scheme not in self.allowed_schemes:
            raise ValueError(
                f"Scheme '{parsed.scheme}' not allowed. Allowed: {', '.join(self.allowed_schemes)}"
            )
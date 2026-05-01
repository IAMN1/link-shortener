from typing import Dict, List

from link_shortener.domain import HashCalculator, OriginalUrl
from link_shortener.application.ports.logger.logger import Logger


class UrlGrouper:
    """
    Validates input URLs, computes their hashes, and groups them for deduplication.

    URLs with an invalid scheme are grouped separately with an error flag.
    """
    def __init__(self, allowed_schemes: List[str], hash_calculator: HashCalculator, logger: Logger):
        """
        Args:
            allowed_schemes: Allowed schemes (e.g., ``['http','https']``).
            hash_calculator: Domain hash calculator.
            logger: Application logger.
        """
        self.allowed_schemes = tuple(allowed_schemes)
        self.hash_calculator = hash_calculator
        self.logger = logger
    
    def group(self, urls: List[str]) -> Dict[str, Dict]:
        """
        Group URLs by their computed hash.

        For each URL:
            - Create an ``OriginalUrl`` value object (validates scheme).
            - Compute the hash.
            - Add to a group keyed by the hash string.
        Invalid URLs are grouped under a synthetic key and marked with an error.

        Args:
            urls: Raw URL strings.

        Returns:
            Dictionary where key is hash (for valid) or ``"invalid_{n}"`` (for invalid).
            Each value is a dict with keys:
                - ``hash``: UrlHash (if valid) else None
                - ``original_url``: OriginalUrl (if valid) else None
                - ``urls``: list of input strings falling into this group
                - ``is_valid``: boolean
                - ``error``: error message if invalid
        """

        groups = {}
        invalid_counter = 0

        for url in urls:
            try:
                original_url = OriginalUrl(url, allowed_schemes=self.allowed_schemes)
                url_hash = self.hash_calculator.calculate(original_url)
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

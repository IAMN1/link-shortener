from typing import Dict, List

from link_shortener.domain import (
    HashCalculator, OriginalUrl, ValidationError
)
from link_shortener.application.ports.logger.logger import Logger


class UrlGrouper:
    """
    Validates input URLs, computes their hashes, and groups them for deduplication.

    URLs the domain refuses are grouped separately with an error flag, so
    one bad entry costs its own item and not the whole batch.
    """
    def __init__(
        self,
        allowed_schemes: List[str],
        max_url_length: int,
        allow_internal_targets: bool,
        hash_calculator: HashCalculator,
        logger: Logger,
    ):
        """
        Args:
            allowed_schemes: Allowed schemes (e.g., ``['http','https']``).
            max_url_length: Longest URL admitted, from ``MAX_URL_LENGTH``.
            allow_internal_targets: Whether destinations inside the
                deployment's own network are admitted.
            hash_calculator: Domain hash calculator.
            logger: Application logger.
        """
        self.allowed_schemes = tuple(allowed_schemes)
        self.max_url_length = max_url_length
        self.allow_internal_targets = allow_internal_targets
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

        groups: Dict[str, Dict] = {}
        invalid_counter = 0

        for url in urls:
            try:
                original_url = OriginalUrl(
                    url,
                    allowed_schemes=self.allowed_schemes,
                    max_length=self.max_url_length,
                    allow_internal_targets=self.allow_internal_targets,
                )
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
            except (ValidationError, ValueError) as e:
                # ``ValidationError`` is a domain error, not a ValueError, so
                # catching only the latter meant nothing was ever caught: a
                # single rejected URL escaped and failed the entire request
                # with a 400, and this whole branch -- the per-item error the
                # response format is built around -- was dead code.
                key = f"invalid_{invalid_counter}"
                invalid_counter += 1
                groups[key] = {
                    "hash": None,
                    "original_url": None,
                    "urls": [url],
                    "is_valid": False,
                    "error": str(e),
                }
                # Same reason as in ``create_short_link``: the URL that
                # reaches this branch is one the domain has just refused,
                # so it is unchecked input and may hold a password. The
                # caller is told which URL failed -- it is echoed back in
                # ``BatchItemResponse`` -- so the log loses no one's
                # ability to find it. ``key`` ties this line to that item.
                self.logger.warning(
                    "Invalid URL in batch", item=key, error=str(e)
                )
        return groups

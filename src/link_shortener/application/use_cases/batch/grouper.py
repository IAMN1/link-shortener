from typing import Dict, List, Tuple

from link_shortener.application.dtos.refusal import Refusal
from link_shortener.application.use_cases.batch.groups import (
    RejectedUrl, UrlGroup,
)
from link_shortener.domain import (
    DomainError, HashCalculator, OriginalUrl, ValidationError
)
from link_shortener.application.ports.logger.logger import Logger


class UrlGrouper:
    """
    Validates input URLs, computes their hashes, and groups them for deduplication.

    URLs the domain refuses are returned separately, so one bad entry costs
    its own item and not the whole batch.
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

    def group(self, urls: List[str]) -> Tuple[List[UrlGroup], List[RejectedUrl]]:
        """
        Group URLs by their computed hash.

        For each URL:
            - Create an ``OriginalUrl`` value object (validates scheme).
            - Compute the hash.
            - Add to the group that hash already has, or open one.

        Returns the two outcomes apart rather than mixed under a flag: the
        caller wanted them apart in every case, and separating them here is
        what lets a group promise a hash instead of carrying ``None``.

        Args:
            urls: Raw URL strings.

        Returns:
            Tuple of the groups, one per distinct address in input order,
            and the URLs the domain refused.
        """

        by_hash: Dict[str, UrlGroup] = {}
        rejected: List[RejectedUrl] = []

        for position, url in enumerate(urls):
            try:
                original_url = OriginalUrl(
                    url,
                    allowed_schemes=self.allowed_schemes,
                    max_length=self.max_url_length,
                    allow_internal_targets=self.allow_internal_targets,
                )
                url_hash = self.hash_calculator.calculate(original_url)
                key = url_hash.value

                if key not in by_hash:
                    by_hash[key] = UrlGroup(
                        hash=url_hash, original_url=original_url
                    )
                by_hash[key].urls.append(url)
            except (ValidationError, ValueError) as e:
                # ``ValidationError`` is a domain error, not a ValueError, so
                # catching only the latter meant nothing was ever caught: a
                # single rejected URL escaped and failed the entire request
                # with a 400, and this whole branch -- the per-item error the
                # response format is built around -- was dead code.
                rejected.append(
                    RejectedUrl(
                        url=url,
                        # The refusal itself, not ``str(e)``. Flattened here,
                        # it reached the boundary as finished English and the
                        # batch answered a Russian reader in a language the
                        # single-link route had already stopped using.
                        refusal=(
                            Refusal.from_error(e)
                            if isinstance(e, DomainError)
                            else Refusal.of(str(e), "VALIDATION_ERROR")
                        ),
                    )
                )
                # Same reason as in ``create_short_link``: the URL that
                # reaches this branch is one the domain has just refused,
                # so it is unchecked input and may hold a password. The
                # caller is told which URL failed -- it is echoed back in
                # ``BatchItemResponse`` -- so the log loses no one's
                # ability to find it.
                #
                # Named by where it sat in the request. The old ``item``
                # counted refusals rather than items -- the second URL of a
                # batch was logged as ``invalid_0`` -- so the one thing the
                # line was for, pointing at an item the address is withheld
                # for, is the one thing it could not do.
                self.logger.warning(
                    "Invalid URL in batch", item=position, error=str(e)
                )
        return list(by_hash.values()), rejected

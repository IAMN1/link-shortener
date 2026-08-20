from typing import Dict, List

from link_shortener.application.dtos.batch import BatchItemResponse
from link_shortener.application.dtos.refusal import Refusal
from link_shortener.domain.i18n import N_
from link_shortener.domain import Link


class BatchResponseBuilder:
    """
    Converts newly created Link entities into ``BatchItemResponse`` objects.

    The first URL in a group is considered the canonical new link; subsequent
    URLs in the same group are marked as duplicates.
    """

    @staticmethod
    def build_from_new_links(
        groups: List[Dict], saved_links: List[Link], base_url: str
    ) -> List[BatchItemResponse]:
        """
        Build response items for groups that resulted in new links.

        Args:
            groups: List of group dicts for which links were newly created.
            saved_links: List of ``Link`` entities that were saved.
            base_url: Base URL for constructing short URLs.

        Returns:
            List of ``BatchItemResponse``, one per input URL.
        """

        results = []
        hash_to_link = {link.url_hash: link for link in saved_links}

        for group in groups:
            link = hash_to_link.get(group["hash"])
            if not link:
                # Safeguard: should not happen, but log missing link for debug
                for url in group["urls"]:
                    results.append(
                        BatchItemResponse.error_(
                            url=url,
                            error=Refusal.of(
                                N_("The link could not be stored"),
                                "LINK_NOT_STORED",
                            ),
                        )
                    )
                continue
            
            # First URL in group -> new link
            results.append(
                BatchItemResponse.success_(
                    url=group["urls"][0],
                    short_code=link.short_code.value,
                    original_url=link.original_url.value,
                    base_url=base_url,
                    clicks=link.clicks,
                    is_new=True,
                    expires_at=link.expires_at,
                    link_id=link.id,
                )
            )

            # Remaining URLs -> duplicates
            for url in group["urls"][1:]:
                results.append(
                    BatchItemResponse.success_(
                        url=url,
                        short_code=link.short_code.value,
                        original_url=link.original_url.value,
                        base_url=base_url,
                        clicks=link.clicks,
                        is_new=False,
                        duplicate_of=link.original_url.value,
                        expires_at=link.expires_at,
                    )
                )
        return results

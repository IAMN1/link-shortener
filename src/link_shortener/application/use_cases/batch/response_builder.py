from typing import Dict, List

from link_shortener.domain import Link
from link_shortener.application.dtos.responses import BatchItemResponse


class BatchResponseBuilder:
    """
    Builds BatchItemResponse objects for newly created links.

    This class is stateless and can be used as a collection of static methods.
    """

    @staticmethod
    def build_from_new_links(
        groups: List[Dict], saved_links: List[Link], base_url: str
    ) -> List[BatchItemResponse]:
        """
        Build response items for groups that resulted in new links.

        For each group, the first URL is considered the original that triggered
        creation; subsequent URLs in the same group are duplicates and get a
        `duplicate_of` field.

        Args:
            groups: List of groups for which new links were created.
            saved_links: List of Link objects that were saved to the repository.
            base_url: Base URL of the service.

        Returns:
            List of BatchItemResponse objects.
        """

        results = []
        hash_to_link = {link.url_hash: link for link in saved_links}

        for group in groups:
            link = hash_to_link.get(group["hash"])
            if not link:
                # Should not happen, but handle gracefully
                for url in group["urls"]:
                    results.append(
                        BatchItemResponse.error_(url=url, error="Failed to save link")
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
                    )
                )
        return results
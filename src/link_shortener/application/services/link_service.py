from dataclasses import dataclass
from typing import List

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.batch import BatchCreateResponse
from link_shortener.application.dtos.link import ExtendedLinkInfoResponse, ShortLinkResponse
from link_shortener.application.dtos.stats import ServiceStatsResponse
from link_shortener.application.use_cases.batch.batch_create_links import BatchCreateLinksUseCase
from link_shortener.application.use_cases.links.create_short_link import CreateShortLinkUseCase
from link_shortener.application.use_cases.links.get_extended_link_info import GetExtendedLinkInfoUseCase
from link_shortener.application.use_cases.links.get_link_info import GetLinkInfoUseCase
from link_shortener.application.use_cases.links.delete_link import DeleteLinkUseCase
from link_shortener.application.use_cases.links.get_user_links import GetUserLinksUseCase
from link_shortener.application.use_cases.links.redirect_link import RedirectLinkUseCase
from link_shortener.application.use_cases.stats.get_service_stats import GetServiceStatsUseCase


@dataclass
class LinkService:
    """
    Application facade for all link-related operations.

    Coordinates the execution of individual use cases and provides a simplified
    interface for the web layer.  Each method delegates directly to the
    corresponding use case.

    Attributes:
        create_short_link_use_case: Use case for creating a single short link.
        get_link_info_use_case: Use case for retrieving basic link information.
        get_extended_link_info_use_case: Use case for extended link analytics.
        redirect_link_use_case: Use case for resolving a short code to its
            original URL.
        batch_create_links_use_case: Use case for batch creation of short links.
        get_service_stats_use_case: Use case for aggregated service statistics.
        get_user_links_use_case: Use case for retrieving a user's links.
    """

    create_short_link_use_case: CreateShortLinkUseCase
    get_link_info_use_case: GetLinkInfoUseCase
    get_extended_link_info_use_case: GetExtendedLinkInfoUseCase
    redirect_link_use_case: RedirectLinkUseCase
    batch_create_links_use_case: BatchCreateLinksUseCase
    get_service_stats_use_case: GetServiceStatsUseCase
    get_user_links_use_case: GetUserLinksUseCase
    delete_link_use_case: DeleteLinkUseCase

    # ------------------------------------------------------------------
    # Single link creation
    # ------------------------------------------------------------------
    def create_short_link(
        self, url: str, context: RequestContext, ttl_seconds: int = 0
    ) -> ShortLinkResponse:
        """Create a single short link.

        Args:
            url: Original URL to shorten.
            context: Request context (contains authentication and metadata).
            ttl_seconds: Time‑to‑live in seconds; 0 means no expiration.

        Returns:
            ShortLinkResponse with the created or existing link details.
        """
        return self.create_short_link_use_case.execute(url, context, ttl_seconds=ttl_seconds)

    # ------------------------------------------------------------------
    # Link information retrieval
    # ------------------------------------------------------------------
    def get_link_info(self, short_code: str, context: RequestContext) -> ShortLinkResponse:
        """Retrieve basic information about a short link.

        Args:
            short_code: The short code.
            context: Request context (authentication required).

        Returns:
            ShortLinkResponse with link metadata.

        Raises:
            LinkNotFoundError: If the short code does not exist.
            DomainError: If the user is not authorized to view the link.
        """
        return self.get_link_info_use_case.execute(short_code, context)

    def get_extended_link_info(
        self, short_code: str, context: RequestContext
    ) -> ExtendedLinkInfoResponse:
        """Retrieve extended analytics for a short link.

        Args:
            short_code: The short code.
            context: Request context (authentication required).

        Returns:
            ExtendedLinkInfoResponse with popularity, age, clicks‑per‑day, etc.

        Raises:
            LinkNotFoundError: If the short code does not exist.
            DomainError: If the user is not authorized.
        """
        return self.get_extended_link_info_use_case.execute(short_code, context)

    # ------------------------------------------------------------------
    # Redirect
    # ------------------------------------------------------------------
    def redirect(self, short_code: str, context: RequestContext) -> str:
        """Resolve a short code to the original URL for an HTTP redirect.

        Click counting is performed asynchronously via a background task.

        Args:
            short_code: The short code.
            context: Request context (IP, User‑Agent for audit).

        Returns:
            The original URL string.

        Raises:
            LinkNotFoundError: If the short code does not exist.
            ValueError: If the short code format is invalid.
        """
        return self.redirect_link_use_case.execute(short_code, context)

    # ------------------------------------------------------------------
    # Batch creation
    # ------------------------------------------------------------------
    def batch_create_short_links(
        self, urls: List[str], context: RequestContext
    ) -> BatchCreateResponse:
        """Create multiple short links in a single request.

        Args:
            urls: List of original URLs (max ``BATCH_CREATE_LIMIT``).
            context: Request context.

        Returns:
            BatchCreateResponse with per‑URL results and aggregates.

        Raises:
            ValueError: If the batch size exceeds the configured limit.
        """
        return self.batch_create_links_use_case.execute(urls, context)

    # ------------------------------------------------------------------
    # Service statistics
    # ------------------------------------------------------------------
    def get_service_stats(self, context: RequestContext) -> ServiceStatsResponse:
        """Retrieve aggregated service‑wide statistics.

        Args:
            context: Request context (user must have ``stats:view_basic``).

        Returns:
            ServiceStatsResponse with total URLs, total clicks, average clicks
            and a list of popular links.
        """
        return self.get_service_stats_use_case.execute(context)

    # ------------------------------------------------------------------
    # Delete link
    # ------------------------------------------------------------------
    def delete_link(self, short_code: str, context: RequestContext) -> bool:
        """Delete a short link by its code.

        Args:
            short_code: The short code to delete.
            context: Request context.

        Returns:
            True if deleted, False if not found.
        """
        return self.delete_link_use_case.execute(short_code, context)

    # ------------------------------------------------------------------
    # User links
    # ------------------------------------------------------------------
    def get_user_links(
        self, user_id: str, context: RequestContext, offset: int = 0, limit: int = 50
    ) -> List[ShortLinkResponse]:
        """Retrieve short links owned by a specific user with pagination.

        Args:
            user_id: UUID of the user.
            context: Request context.
            offset: Number of links to skip (default 0).
            limit: Maximum number of links to return (default 50, max 200).

        Returns:
            List of ShortLinkResponse objects belonging to the user.
        """
        return self.get_user_links_use_case.execute(user_id, context, offset=offset, limit=limit)

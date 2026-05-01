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
from link_shortener.application.use_cases.links.redirect_link import RedirectLinkUseCase
from link_shortener.application.use_cases.stats.get_service_stats import GetServiceStatsUseCase


@dataclass
class LinkService:
    """
    Application facade for all link-related operations.

    Coordinates the execution of individual use cases and hides
    their orchestration from the web layer.
    """

    create_short_link_use_case: CreateShortLinkUseCase
    get_link_info_use_case: GetLinkInfoUseCase
    get_extended_link_info_use_case: GetExtendedLinkInfoUseCase
    redirect_link_use_case: RedirectLinkUseCase
    batch_create_links_use_case: BatchCreateLinksUseCase
    get_service_stats_use_case: GetServiceStatsUseCase

    def create_short_link(
        self, url: str, context: RequestContext) -> ShortLinkResponse:
        """
        Create a single short link.

        Args:
            url: Original URL to shorten.
            context: Request context.

        Returns:
            ShortLinkResponse with the created or existing link details.
        """
        return self.create_short_link_use_case.execute(url, context)

    def get_link_info(self, short_code: str, context: RequestContext) -> ShortLinkResponse:
        """
        Retrieve basic link information.

        Args:
            short_code: The short code.
            context: Request context.

        Returns:
            ShortLinkResponse.
        """
        return self.get_link_info_use_case.execute(short_code, context)

    def get_extended_link_info(self, short_code: str, context: RequestContext) -> ExtendedLinkInfoResponse:
        """
        Retrieve extended link statistics.

        Args:
            short_code: The short code.
            context: Request context.

        Returns:
            ExtendedLinkInfoResponse with derived metrics.
        """
        return self.get_extended_link_info_use_case.execute(short_code, context)

    def redirect(
        self, short_code: str, context: RequestContext) -> str:
        """
        Get the original URL for a redirect, asynchronously updating stats.

        Args:
            short_code: The short code.
            context: Request context.

        Returns:
            The original URL string.
        """
        return self.redirect_link_use_case.execute(short_code, context)

    def batch_create_short_links(
        self, urls: List[str], context: RequestContext) -> BatchCreateResponse:
        """
        Batch create short links.

        Args:
            urls: List of original URLs.
            context: Request context.

        Returns:
            BatchCreateResponse with per-URL results and aggregates.
        """
        return self.batch_create_links_use_case.execute(urls, context)

    def get_service_stats(self, context: RequestContext) -> ServiceStatsResponse:
        """
        Retrieve aggregated service statistics.

        Args:
            context: Request context.

        Returns:
            ServiceStatsResponse.
        """
        return self.get_service_stats_use_case.execute(context)

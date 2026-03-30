from dataclasses import dataclass
from typing import List

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.responses import BatchCreateResponse, ExtendedLinkInfoResponse, ServiceStatsResponse, ShortLinkResponse
from link_shortener.application.use_cases.batch.batch_create_links import BatchCreateLinksUseCase
from link_shortener.application.use_cases.create_short_link import CreateShortLinkUseCase
from link_shortener.application.use_cases.get_link_info import GetExtendLinkInfoUseCase, GetLinkInfoUseCase
from link_shortener.application.use_cases.get_service_stats import GetServiceStatsUseCase
from link_shortener.application.use_cases.redirect_link import RedirectLinkUseCase


@dataclass
class LinkService:
    """
    Application service that acts as a facade for all link-related use cases.

    This service coordinates the execution of use cases and provides a simple,
    unified interface for the web layer. It does not contain business logic
    itself but delegates to the appropriate use cases.
    """

    create_short_link_use_case: CreateShortLinkUseCase
    get_link_info_use_case: GetLinkInfoUseCase
    get_extended_link_info_use_case: GetExtendLinkInfoUseCase
    redirect_link_use_case: RedirectLinkUseCase
    batch_create_links_use_case: BatchCreateLinksUseCase
    get_service_stats_use_case: GetServiceStatsUseCase

    def create_short_link(
        self, url: str, context: RequestContext) -> ShortLinkResponse:
        """
        Create a short link for the given URL.

        Delegates to CreateShortLinkUseCase.

        Args:
            url: Original URL to shorten.
            context: Request context with client metadata.

        Returns:
            ShortLinkResponse DTO.
        """
        return self.create_short_link_use_case.execute(url, context)

    def get_link_info(self, short_code: str, context: RequestContext) -> ShortLinkResponse:
        """
        Retrieve basic information about a short link.

        Delegates to GetLinkInfoUseCase.

        Args:
            short_code: Short code of the link.
            context: Request context with client metadata.

        Returns:
            ShortLinkResponse DTO.
        """
        return self.get_link_info_use_case.execute(short_code, context)

    def get_extended_link_info(self, short_code: str, context: RequestContext) -> ExtendedLinkInfoResponse:
        """
        Retrieve extended information about a short link.

        Delegates to GetExtendLinkInfoUseCase.

        Args:
            short_code: Short code of the link.
            context: Request context with client metadata.

        Returns:
            ExtendedLinkInfoResponse DTO.
        """
        return self.get_extended_link_info_use_case.execute(short_code, context)

    def redirect(
        self, short_code: str, context: RequestContext) -> str:
        """
        Get the original URL for redirect (increments click count).

        Delegates to RedirectLinkUseCase.

        Args:
            short_code: Short code of the link.
            context: Request context with client metadata.

        Returns:
            Original URL as string.
        """
        return self.redirect_link_use_case.execute(short_code, context)

    def batch_create_short_links(
        self, urls: List[str], context: RequestContext) -> BatchCreateResponse:
        """
        Create short links for multiple URLs in batch.

        Delegates to BatchCreateLinksUseCase.

        Args:
            urls: List of URLs to shorten.
            context: Request context with client metadata.

        Returns:
            BatchCreateResponse DTO with aggregated results.
        """
        return self.batch_create_links_use_case.execute(urls, context)

    def get_service_stats(self, context: RequestContext) -> ServiceStatsResponse:
        """
        Get service-wide statistics.

        Delegates to GetServiceStatsUseCase.

        Args:
            context: Request context with client metadata.

        Returns:
            ServiceStatsResponse DTO.
        """
        return self.get_service_stats_use_case.execute(context)

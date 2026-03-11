from dataclasses import dataclass
from typing import List, Optional

from link_shortener.application.dtos.responses import BatchCreateResponse, ExtendedLinkInfoResponse, ServiceStatsResponse, ShortLinkResponse
from link_shortener.application.use_cases.batch_create_links import BatchCreateLinksUseCase
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
        self, url: str, user_ip: Optional[str] = None, user_agent: Optional[str] = None
    ) -> ShortLinkResponse:
        """
        Create a short link for the given URL.

        Delegates to CreateShortLinkUseCase.

        Args:
            url: Original URL to shorten.
            user_ip: Client IP address (for audit). Optional.
            user_agent: Client User-Agent (for audit). Optional.

        Returns:
            ShortLinkResponse DTO.
        """
        return self.create_short_link_use_case.execute(
            url, user_ip, user_agent
        )

    def get_link_info(self, short_code: str) -> ShortLinkResponse:
        """
        Retrieve basic information about a short link.

        Delegates to GetLinkInfoUseCase.

        Args:
            short_code: Short code of the link.

        Returns:
            ShortLinkResponse DTO.
        """
        return self.get_link_info_use_case.execute(short_code)

    def get_extended_link_info(self, short_code: str) -> ExtendedLinkInfoResponse:
        """
        Retrieve extended information about a short link.

        Delegates to GetExtendLinkInfoUseCase.

        Args:
            short_code: Short code of the link.

        Returns:
            ExtendedLinkInfoResponse DTO.
        """
        return self.get_extended_link_info_use_case.execute(short_code)

    def redirect(
        self, short_code: str, user_ip: Optional[str] = None, user_agent: Optional[str] = None
    ) -> str:
        """
        et the original URL for redirect (increments click count).

        Delegates to RedirectLinkUseCase.

        Args:
            short_code: Short code of the link.
            user_ip: Client IP address (for audit). Optional.
            user_agent: Client User-Agent (for audit). Optional.

        Returns:
            Original URL as string.
        """
        return self.redirect_link_use_case.execute(
            short_code, user_ip, user_agent
        )

    def batch_create_short_links(
        self, urls: List[str], user_ip: Optional[str] = None, user_agent: Optional[str] = None
    ) -> BatchCreateResponse:
        """
        Create short links for multiple URLs in batch.

        Delegates to BatchCreateLinksUseCase.

        Args:
            urls: List of URLs to shorten.
            user_ip: Client IP address (for audit). Optional.
            user_agent: Client User-Agent (for audit). Optional.

        Returns:
            BatchCreateResponse DTO with aggregated results.
        """
        return self.batch_create_links_use_case.execute(
            urls, user_ip, user_agent
        )

    def get_service_stats(self) -> ServiceStatsResponse:
        """
        Get service-wide statistics.

        Delegates to GetServiceStatsUseCase.

        Returns:
            ServiceStatsResponse DTO.
        """
        return self.get_service_stats_use_case.execute()

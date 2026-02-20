from dataclasses import dataclass
from typing import List

from link_shortener.application.dtos.responses import BatchCreateResponse, ServiceStatsResponse, ShortLinkResponse
from link_shortener.application.use_cases.batch_create_links import BatchCreateLinksUseCase
from link_shortener.application.use_cases.create_short_link import CreateShortLinkUseCase
from link_shortener.application.use_cases.get_link_info import GetLinkInfoUseCase
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
    redirect_link_use_case: RedirectLinkUseCase
    batch_create_links_use_case: BatchCreateLinksUseCase
    get_service_stats_use_case: GetServiceStatsUseCase

    def create_short_link(self, url: str) -> ShortLinkResponse:
        """
        Create a short link for the given URL.

        Delegates to CreateShortLinkUseCase.

        Args:
            url (str): Original URL to shorten.
            **kwargs: Additional arguments (e.g., user_ip, user_agent) 
                passed to the use case.

        Returns:
            ShortLinkResponse: ShortLinkResponse DTO.
        """
        return self.create_short_link_use_case.execute(url)

    def get_link_info(self, short_code: str) -> ShortLinkResponse:
        """
        Retrieve information about a short link.

        Delegates to GetLinkInfoUseCase.

        Args:
            short_code (str): Short code of the link.

        Returns:
            ShortLinkResponse: ShortLinkResponse DTO.
        """
        return self.get_link_info_use_case.execute(short_code)

    def redirect(self, short_code: str) -> str:
        """
        Get the original URL for redirect (increments click count).

        Delegates to RedirectLinkUseCase.

        Args:
            short_code (str): Short code of the link.
            **kwargs: Additional arguments (e.g., user_ip, user_agent).

        Returns:
            str: Original URL as string.
        """
        return self.redirect_link_use_case.execute(short_code)

    def batch_create_short_links(self, urls: List[str]) -> BatchCreateResponse:
        """
        Create short links for multiple URLs in batch.

        Delegates to BatchCreateLinksUseCase.

        Args:
            urls (List[str]): List of URLs to shorten.
            **kwargs: Additional arguments (e.g., user_ip, user_agent).

        Returns:
            BatchCreateResponse: BatchCreateResponse DTO 
                with aggregated results.
        """
        return self.batch_create_links_use_case.execute(urls)

    def get_service_stats(self) -> ServiceStatsResponse:
        """
        Get service-wide statistics.

        Delegates to GetServiceStatsUseCase.

        Returns:
            ServiceStatsResponse: ServiceStatsResponse DTO.
        """
        return self.get_service_stats_use_case.execute()

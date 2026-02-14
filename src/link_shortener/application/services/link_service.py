from dataclasses import dataclass
from typing import List

from link_shortener.application import (BatchCreateLinksUseCase,
                                        BatchCreateResponse,
                                        CreateShortLinkUseCase,
                                        GetLinkInfoUseCase,
                                        GetServiceStatsUseCase,
                                        RedirectLinkUseCase,
                                        ServiceStatsResponse,
                                        ShortLinkResponse)


@dataclass
class LinkService:
    """
    Application Service - фасад для use cases
    Координирует работу use cases
    """

    create_short_link_use_case: CreateShortLinkUseCase
    get_link_info_use_case: GetLinkInfoUseCase
    redirect_link_use_case: RedirectLinkUseCase
    batch_create_links_use_case: BatchCreateLinksUseCase
    get_service_stats_use_case: GetServiceStatsUseCase

    def create_short_link(self, url: str) -> ShortLinkResponse:
        """Создание сокращенной ссылки"""
        return self.create_short_link_use_case.execute(url)

    def get_link_info(self, short_code: str) -> ShortLinkResponse:
        """Получение информации о ссылке"""
        return self.get_link_info_use_case.execute(short_code)

    def redirect(self, short_code: str) -> str:
        """Редирект на оригинальный URL"""
        return self.redirect_link_use_case.execute(short_code)

    def batch_create_short_links(self, urls: List[str]) -> BatchCreateResponse:
        """Пакетное создание сокращенных ссылок"""
        return self.batch_create_links_use_case.execute(urls)

    def get_service_stats(self) -> ServiceStatsResponse:
        """Получение статистики по сервису сокращенных ссылок"""
        return self.get_service_stats_use_case.execute()

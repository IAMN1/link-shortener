from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from link_shortener.domain.entities.link import Link
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.url_hash import UrlHash


class LinkRepository(ABC):
    """Интерфейс для работы с хранилизем ссылок"""

    @abstractmethod
    def save(self, link: Link) -> Link:
        """Сохранение ссылки"""
        pass

    @abstractmethod
    def save_many(self, links: list[Link]) -> List[Link]:
        """Пакетное сохранение нескольких ссылок"""
        pass

    @abstractmethod
    def find_by_code(self, short_code: ShortCode) -> Optional[Link]:
        """Поиск ссылки по коду"""
        pass

    @abstractmethod
    def find_by_codes(self, short_codes: List[ShortCode]) -> Dict[ShortCode, Optional[Link]]:
        """Пакетный поиск ссылкок по кодам"""
        pass

    @abstractmethod
    def find_by_hash(self, url_hash: UrlHash) -> Optional[Link]:
        """Поиск ссылки по хэшу URL"""
        pass

    @abstractmethod
    def find_by_hashes(self, url_hashes: List[UrlHash]) -> Dict[UrlHash, Optional[Link]]:
        """Пакетный поиск поиск ссылок по хэшам"""
        pass

    @abstractmethod
    def increment_clicks(self, short_code: ShortCode) -> None:
        """Увеличение счетчика кликов по ссылке"""
        pass

    @abstractmethod
    def increment_clicks_batch(self, short_codes: List[ShortCode]) ->  None:
        """Пакетное увеличение счетчика кликов"""
        pass

    @abstractmethod
    def get_stats(self) -> dict:
        """
        Получение статистики по ссылке 
        (с полной информацией о ней)
        """
        pass

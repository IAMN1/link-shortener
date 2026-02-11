

from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from domain.entities.link import Link
from domain.value_objects.short_code import ShortCode
from domain.value_objects.url_hash import UrlHash


class LinkCache(ABC):
    """
    Интерфейс для кэширования объектов Link
    """

    @abstractmethod
    def get_by_code(self, short_code: ShortCode) -> Optional[Link]:
        """Получение ссылки по коду"""
        pass

    @abstractmethod
    def get_by_hash(self, url_hash: UrlHash) -> Optional[Link]:
        """Получение ссылки по хэшу URL"""
        pass

    @abstractmethod
    def get_by_hashes(self, url_hashes: List[UrlHash]) -> Dict[UrlHash, Optional[Link]]:
        """Получение ссылок по хэшам (пакетная обработка)"""
        pass
    
    @abstractmethod
    def save(self, link: Link) -> None:
        """Сохранение ссылки в кэш"""
        pass

    @abstractmethod
    def save_many(self, links: List[Link]) -> None:
        """Пакетное сохранение нескольких ссылок (пакетная обработка)"""
        pass

    @abstractmethod
    def delete(self, short_code: ShortCode) -> None:
        """Удаление ссылки из кэша по короткому коду."""
        pass


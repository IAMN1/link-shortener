"""
( Порт / Интерфейс ) для работы с хранилищем ссылок.  
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple

from ...entities.link import Link


class ILinkRepository(ABC):
    """Порт для работы с хранилещем ссылок"""

    @abstractmethod
    def create(self, link: Link) -> Link:
        """Создание новой ссылки"""
        pass

    @abstractmethod
    def create_or_get(source_url: str, url_hash: str, short_code: str) -> Tuple[Link, bool]:
        """Создает или получает существующую ссылку"""
        pass
    
    @abstractmethod
    def bulk_create(self, links_data: List[Dict]) -> List[Link]:
        """Пакетное создание ссылок"""
        pass

    @abstractmethod
    def get_by_short_code(self, short_code: str) -> Optional[Link]:
        """Извлечение ссылки по короткому коду"""
        pass

    @abstractmethod
    def get_by_hash(self, url_hash: str) -> Optional[Link]:
        """Извлечение ссылки по кэшу URL"""
        pass

    @abstractmethod
    def get_by_hashes(self, url_hashes: List[str]) -> List[Link]:
        """Пакетное извлечение ссылок по хэшам"""
        pass

    @abstractmethod
    def increment_clicks(self, short_code: str) -> bool:
        """Инкрементирует счетчик переходов"""
        pass

    @abstractmethod
    def get_stats(self) -> Dict:
        """Извлечение статистики сервиса"""
        pass

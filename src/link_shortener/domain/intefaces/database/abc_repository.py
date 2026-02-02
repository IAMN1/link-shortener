from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple

from link_shortener.domain.entities.link import Link


class ILinkRepository(ABC):
    """Порт для работы с хранилещем ссылок"""

    @abstractmethod
    def create(self, link: Link) -> Link:
        pass

    @abstractmethod
    def create_or_get(source_url: str, url_hash: str, short_code: str) -> Tuple[Link, bool]:
        pass
    
    @abstractmethod
    def bulk_create(self, links_data: List[Dict]) -> List[Link]:
        pass

    @abstractmethod
    def get_by_short_code(self, short_code: str) -> Optional[Link]:
        pass

    @abstractmethod
    def get_by_hash(self, url_hash: str) -> Optional[Link]:
        pass

    @abstractmethod
    def get_by_hashes(self, url_hashes: List[str]) -> List[Link]:
        pass

    @abstractmethod
    def increment_clicks(self, short_code: str) -> bool:
        pass

    @abstractmethod
    def get_stats(self) -> Dict:
        pass

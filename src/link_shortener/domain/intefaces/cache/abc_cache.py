from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

class ICacheClient(ABC):
    """Абстракция для кэширования"""
    @abstractmethod
    def get(self, key: str) -> str:
        pass

    @abstractmethod
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        pass

    @abstractmethod
    def get_many(self, keys: List[str]) -> Dict[str, Any]:
        pass

    @abstractmethod
    def set_many(self, data: Dict[str, Any], ttl: Optional[int]) -> bool:
        pass

    @abstractmethod
    def clear(self) -> bool:
        pass

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    def close(self) -> None:
        pass
"""
(Порт / Интерфейс) для кэширования. 
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

class ICacheClient(ABC):
    """Абстракция для кэширования"""
    
    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        """Получение значения из кэша"""
        pass

    @abstractmethod
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Запись значения в кэш"""
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Удаление значения из кэша"""
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Проверка существования ключа в кэше"""
        pass

    @abstractmethod
    def get_many(self, keys: List[str]) -> Dict[str, Any]:
        """Получение нескольких значений за один запрос"""
        pass

    @abstractmethod
    def set_many(self, data: Dict[str, Any], ttl: Optional[int] = None) -> bool:
        """Установка нескольких значений за один запрос"""
        pass

    @abstractmethod
    def clear(self) -> bool:
        """Очистка всего кэша"""
        pass

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики использования кэша"""
        pass

    @abstractmethod
    def close(self) -> None:
        """Закрытие соединения с кэшем"""
        pass
from abc import ABC, abstractmethod
from typing import Optional


class StatsCache(ABC):
    """Интерфейс для кэширования статистики сервиса"""

    @abstractmethod
    def get_stats(self) -> Optional[dict]:
        """Получение статистики"""
        pass

    @abstractmethod
    def save_stats(slef, stats: dict) -> None:
        """Сохранение статистики"""
        pass

    @abstractmethod
    def delete_stats(self) -> None:
        """Удаление статистики"""
        pass
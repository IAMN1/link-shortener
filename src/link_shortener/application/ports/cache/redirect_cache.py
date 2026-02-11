from abc import ABC, abstractmethod
from typing import Optional

from src.link_shortener.domain.value_objects.short_code import ShortCode


class RedirectCache(ABC):
    """Интерфейс для кэширования URL для быстрого редиректа"""
    
    @abstractmethod
    def get_original_url(self, short_code: ShortCode) -> Optional[str]:
        """Получение оригинальной ссылки"""
        pass

    @abstractmethod
    def save_original_url(self, short_code: ShortCode, original_url: str) -> None:
        """Сохранение оригинальной ссылки в кэш для редиректа"""
        pass
    
    # @abstractmethod
    # def delete_original_url(self, short_code: ShortCode) -> None:
    #     """Удаление URL для редиректа"""
    #     pass
from abc import ABC, abstractmethod
from typing import Optional, Tuple


class IShortCodeExtractor(ABC):
    """Интерфейс для извлечения короткого кода из полной короткой ссылки"""
    @abstractmethod
    def extract_code_from_url(self, short_url: str) -> Optional[str]:
        """
        Извлекает короткий код из полной короткой ссылки

        Args:
            short_url: Полная короткая ссылка (например, https://sh.ort/code123)

        Returns:
            Короткий код или None, если извлечение не удалось
        """
        pass
    @abstractmethod
    def validate_short_url_format(self, short_url: str) -> Tuple[bool, str]:
        """
        Проверяет формат короткой ссылки

        Args:
            short_url: Полная короткая ссылка

        Returns:
            Tuple[bool, str]: (Успех, Сообщение об ошибке)
        """
        pass
    @abstractmethod
    def get_base_url(self) -> str:
        """
        Возвращает базовый URL сервиса
        """
        pass

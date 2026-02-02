"""
( Порт / Интерфейс ) для валидации URL адресов.
"""

from abc import ABC, abstractmethod
from typing import Tuple


class IUrlValidator(ABC):
    """Интерфейс для валидации URL адресов"""

    @abstractmethod
    def is_valid_url(self, url: str) -> Tuple[bool, str]:
        """Метод проверки на валидность и безопасность"""
        pass

    @abstractmethod
    def normalize_url(self, url: str) -> str:
        """Метод нормализации url для устранения дубликатов"""
        pass

    @abstractmethod
    def extract_domain(self, url: str) -> str:
        """Метод извлечения домена из url"""
        pass
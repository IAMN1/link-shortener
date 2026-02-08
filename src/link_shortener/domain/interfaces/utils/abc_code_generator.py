"""
(Порт / Интерфейс) для генерации коротких кодов
"""

from abc import ABC, abstractmethod
from typing import Tuple


class ICodeGenerator(ABC):
    """Интерфейс для генерации коротких кодов"""

    @abstractmethod
    def generate_code(self, normalized_url: str) -> str:
        """Генерация короткого кода для cсылки"""
        pass

    @abstractmethod
    def calculate_deduplication_hash(self, normalized_url: str) -> str:
        """Вычисление хэша для дедупликации"""
        pass

    @abstractmethod
    def calculate_entropy(self, code_length: int) -> Tuple[float, int]:
        """Расчет энтропии для оценки безопасности"""
        pass

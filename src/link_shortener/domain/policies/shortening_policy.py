from abc import ABC, abstractmethod

from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.url_hash import UrlHash


class ShorteningPolicy(ABC):
    """Доменная политика - бизнес-правила генерации кодов"""

    @abstractmethod
    def calculate_hash(self, original_url: OriginalUrl) -> UrlHash:
        """Вычисление хэша для дедупликации"""
        pass

    @abstractmethod
    def generate_code(self, original_url: OriginalUrl) -> ShortCode:
        """Генеарция короткого кода по URL"""
        pass


class HashBasedShorteningPolicy(ShorteningPolicy):
    """
    Детерминированная реализация политики на основе хэширования.
    Один URL = один код
    """

    def __init__(self, code_length: int = 7):
        self.code_length = code_length
    
    def calculate_hash(self, original_url: OriginalUrl) -> UrlHash:
        import hashlib

        # Нормализация URL для дедупликации
        normalized = original_url.normalize()
        url_hash = hashlib.sha256(normalized.encode()).hexdigest()

        return UrlHash(url_hash)
    
    def generate_code(self, original_url: OriginalUrl) -> ShortCode:
        import hashlib
        import base64

        # Детерминированная генерация на основе хэша URL
        normalized = original_url.normalize()
        url_hash = hashlib.sha256(normalized.encode()).digest()
        short_bytes = base64.urlsafe_b64encode(url_hash[:self.code_length])
        short_code = short_bytes.decode().rstrip('=')

        return ShortCode(short_code[:self.code_length])
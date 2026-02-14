from abc import ABC, abstractmethod
import base64
import hashlib

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
    def generate_code(self, input_str: str) -> ShortCode:
        """Генеарция короткого кода на основе произвольной строки"""
        pass
    
    @abstractmethod
    def generate_code_for_url(self, original_url: OriginalUrl) -> ShortCode:
        """Генерация кода для URL (использует нормализованную строку)"""
        return self.generate_code(original_url.normalize())

class HashBasedShorteningPolicy(ShorteningPolicy):
    """
    Детерминированная реализация политики на основе хэширования.
    Один URL = один код
    """

    def __init__(self, code_length: int = 7, min_length: int = 6, max_length: int = 10):
        
        if not (min_length <= code_length <= max_length):
            raise ValueError(f'code_length must be between {min_length} and {max_length}')
        
        self.code_length = code_length
        self.min_length = min_length
        self.max_length = max_length
    
    def calculate_hash(self, original_url: OriginalUrl) -> UrlHash:

        # Нормализация URL для дедупликации
        normalized = original_url.normalize()
        url_hash = hashlib.sha256(normalized.encode()).hexdigest()

        return UrlHash(url_hash)
    
    def generate_code(self, input_string: str) -> ShortCode:

        # Детерминированная генерация на основе хэша URL

        # Используем достаточно байт, чтобы после кодирования
        # получить не менее min_length символов
        need_bytes = max(self.code_length, self.min_length) * 8 // 6 + 1
        hash_bytes = hashlib.sha256(input_string.encode()).digest()[:need_bytes]
        short_bytes = base64.urlsafe_b64encode(hash_bytes)
        short_code = short_bytes.decode().rstrip('=')[:self.code_length]

        return ShortCode(short_code)
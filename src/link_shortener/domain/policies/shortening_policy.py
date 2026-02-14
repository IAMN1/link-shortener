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
    def generate_code(self, input_str: str) -> ShortCode:
        """Генеарция короткого кода на основе произвольной строки"""
        pass

    def generate_code_for_url(self, original_url: OriginalUrl) -> ShortCode:
        """Генерация кода для URL (использует нормализованную строку)"""
        return self.generate_code(original_url.normalize())

    def generate_unique_code(
        self, original_url: OriginalUrl, attempt: int = 0
    ) -> ShortCode:
        """
        Генерация кода с возможностью добавления соли для разрешения коллизий.
        При attempt > 0 к нормализованному URL добавляется суффикс,
        чтобы сгенерировать другой код без изменения оригинального URL.
        """
        base = original_url.normalize()
        if attempt == 0:
            return self.generate_code(base)
        salted = f"{base}#collision_{attempt}"
        return self.generate_code(salted)

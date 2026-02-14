from typing import Any, Dict


class CacheKeyGenerator:
    """Генератор ключей для кэша"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.prefix = config.get("CACHE_LINK_PREFIX", "link_shortener")

    def _build_key(self, *parts: str) -> str:
        """Построение ключа с префиксом"""
        key_parts = [self.prefix] + list(parts)
        return ":".join(key_parts)

    def for_redirect(self, short_code: str) -> str:
        """
        Ключ для быстрого редиректа
        Используется для быстрого редиректа (L1)
        """
        return self._build_key("redirect", short_code)

    def for_short_code(self, short_code: str) -> str:
        """
        Ключ для получения информации о ссылке
        Используется при записи/извлечении ссылки (L2)
        """
        return self._build_key("code", short_code)

    def for_url_hash(self, url_hash: str) -> str:
        """
        Ключ для дедупликации по хэшу
        Используется для проверки есть ли такая ссылка перед созданием
        """
        return self._build_key("hash", url_hash)

    def for_stats(self) -> str:
        """Ключ для статистики по сервису"""
        return self._build_key("stats", "global")

from abc import ABC
from dataclasses import dataclass


@dataclass
class CacheKeyStrategy(ABC):
    """Протокол для стратегий формирования ключей кэша"""
    
    def get_key(self, *args, **kwargs) -> str:
        """генерирует ключ кэша"""
        pass

@dataclass
class HashCacheStrategy(CacheKeyStrategy):
    """
    Стратегия используется для проверки ссылки на дедупликацию по хэшу
    url_hash -> short_code
    """
    prefix: str = 'link:hash:'

    def get_key(self, url_hash: str) -> str:
        return f"{self.prefix}{url_hash}"

@dataclass
class RedirectCacheStrategy(CacheKeyStrategy):
    """
    Стратегия используется для редиректа из кэша
    short_code -> original_url
    """
    prefix: str = 'link:redirect:'

    def get_key(self, short_code: str) -> str:
        return f'{self.prefix}{short_code}'

@dataclass
class InfoCacheStrategy(CacheKeyStrategy):
    """
    Стратегия используется для получения полной информации о ссылке
    short_code -> link
    """
    prefix: str = 'link:info:'

    def get_key(self, short_code: str) -> str:
        return f'{self.prefix}{short_code}'

@dataclass
class StatsCacheStrategy(CacheKeyStrategy):
    """
    Стратегия для ключей статистики
    Используется для возврата статистики из кэша
    """
    prefix: str = 'link:stats:'

    def get_key(self) -> str:
        return f'{self.prefix}global'
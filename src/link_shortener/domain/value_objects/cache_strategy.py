from dataclasses import dataclass
from typing import Protocol


class CacheKeyStrategy(Protocol):
    def get_key(self, identifier: str) -> str:
        ...
    

@dataclass(frozen=True)
class RedirectCacheStrategy:
    prefix: str = "redirect:"

    def get_key(self, short_code: str) -> str:
        return f"{self.prefix}{short_code}"

@dataclass(frozen=True)
class HashCahcheStrategy:
    prefix: str = "hash:"

    def get_key(self, url_hash: str) -> str:
        return f'{self.prefix}{url_hash}'


@dataclass(frozen=True)
class StatsCacheStrategy:
    prefix: str = "stats:"

    def get_key(self) -> str:
        return f'{self.prefix}'
    
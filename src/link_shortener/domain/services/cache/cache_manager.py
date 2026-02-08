from datetime import datetime
from typing import Any, Dict, List, Optional

from ...entities.link import Link
from ...interfaces.cache.abc_cache import ICacheClient
from ...interfaces.logger.abc_logger import ILogger
from ...value_objects.cache_strategy import (
    CacheKeyStrategy,
    InfoCacheStrategy,
    RedirectCacheStrategy,
)
from ..base_service import BaseService

# TODO Дописать получение статистики get_service_stats
# в данных есть вложенные значения!
# продумать, как обрабатывать запись и извлечение кэша


class CacheManager(BaseService):
    """менеджер для работы с кэшем ссылок"""

    def __init__(
        self,
        logger: Optional[ILogger] = None,
        cache_client: Optional[ICacheClient] = None,
    ):
        super().__init__(logger)
        self._cache_client = cache_client

    def _link_to_dict(self, link: Link) -> Dict[str, Any]:
        """Конвертация Link в словарь для кэширования"""
        return {
            "id": link.id,
            "url_hash": link.url_hash,
            "short_code": link.short_code,
            "original_url": link.original_url,
            "created_at": link.created_at.isoformat(),
            "clicks": link.clicks,
            "last_accessed": (
                link.last_accessed.isoformat() if link.last_accessed else None
            ),
        }

    def _dict_to_link(self, data: Dict[str, Any]) -> Link:
        """Конвертация из словаря из кэша в LINK сущность"""
        return Link(
            id=data["id"],
            url_hash=data["url_hash"],
            short_code=data["short_code"],
            original_url=data["original_url"],
            created_at=datetime.fromisoformat(data["created_at"]),
            clicks=data["clicks"],
            last_accessed=(
                datetime.fromisoformat(data["last_accessed"])
                if data["last_accessed"]
                else None
            ),
        )

    def get_original_url(
        self, short_code: str, strategy: Optional[RedirectCacheStrategy] = None
    ) -> Optional[str]:
        """
        Получение оригинального URL из кэша для редиректа

        Args:
            short_code: Короткий код ссылки
            strategy: Стратегия редиректа

        Returns:
            Оригинальный URL или None
        """
        result = None
        if not self._cache_client or not strategy:
            return result

        cache_key = strategy.get_key(short_code)
        cached_data = self._cache_client.get(cache_key)

        if isinstance(cached_data, str):
            result = cached_data

        elif isinstance(cached_data, dict):
            self._log_warning(
                "В кэше для редиректа найден словарь вместо строки",
                short_code=short_code,
            )
            result = cached_data.get("original_url", None)

        return result

    def get_link_info(
        self, short_code: str, strategy: Optional[InfoCacheStrategy] = None
    ) -> Optional[Link]:
        """
        Получение ссылки из кэша

        Args:
            short_code: Короткий код ссылки
            strategy: Стратегия информации

        Returns:
            Объект Link или None
        """
        result = None
        if not self._cache_client or not strategy:
            return result
        cache_key = strategy.get_key(short_code)
        cached_data = self._cache_client.get(cache_key)

        if isinstance(cached_data, dict):
            try:
                result = self._dict_to_link(cached_data)
            except Exception as e:
                self._log_error("Ошибка десериализации из кэша", error=str(e))

        return result

    def get_link_by_hash(
        self, url_hash: str, strategy: Optional[CacheKeyStrategy] = None
    ) -> Optional[Link]:
        """
        Получение ссылки из кэша по хэшу

        Args:
            url_hash: Хэш URL
            strategy: Стратегия хэширования

        Returns:
            Объект Link или None
        """
        if not self._cache_client or not strategy:
            return None

        cache_key = strategy.get_key(url_hash)
        cached_data = self._cache_client.get(cache_key)

        if isinstance(cached_data, dict):
            try:
                return self._dict_to_link(cached_data)
            except Exception as e:
                self._log_error("Ошибка десериализации из кэша", error=str(e))
        return None

    def get_link_by_hashes(
        self, url_hashes: List[str], strategy: Optional[CacheKeyStrategy] = None
    ) -> List[Link]:
        """Получение нескольких ссылок по хэшам

        Args:
            url_hashes: Список хэшей URL
            strategy: Стратегия хэширования

        Returns:
            Список объектов Link
        """
        if not self._cache_client or not strategy:
            return []

        cache_keys = [strategy.get_key(hash_) for hash_ in url_hashes]
        cached_data = self._cache_client.get_many(cache_keys)

        links = []
        for key, data in cached_data.items():
            if isinstance(data, dict):
                try:
                    links.append(self._dict_to_link(data))
                except Exception as e:
                    self._log_error("Ошибка десериализации", error=str(e), key=key)
        return links

    def cache_link(
        self, link: Link, strategies: Dict[str, CacheKeyStrategy], ttl: int = 3600
    ) -> bool:
        """Кэширование ссылки по всем стратегиям"""
        if not self._cache_client:
            return False

        link_dict = self._link_to_dict(link)
        cache_data = {}

        for name, strategy in strategies.items():
            if name == "hash":
                cache_key = strategy.get_key(link.url_hash)
                cache_data[cache_key] = link_dict
            elif name == "redirect":
                cache_key = strategy.get_key(link.short_code)
                cache_data[cache_key] = link.original_url
            elif name == "info":
                cache_key = strategy.get_key(link.short_code)
                cache_data[cache_key] = link_dict

        if cache_data:
            return self._cache_client.set_many(cache_data, ttl)
        return False

    def cache_links(
        self,
        links: List[Link],
        strategies: Dict[str, CacheKeyStrategy],
        ttl: int = 3600,
    ) -> bool:
        """массовое кэширование ссылок за один запрос"""
        success = False
        if not self._cache_client or not links:
            return success

        start_time = datetime.now()
        link_count = len(links)
        strategy_count = len(strategies)

        self._log_info(
            "Начало массового кэширования ссылок",
            link_count=link_count,
            strategy_count=strategy_count,
            estimated_keys=link_count * strategy_count,
        )

        cache_data = {}

        for link in links:
            link_dict = self._link_to_dict(link)
            for name, strategy in strategies.items():
                if name == "hash":
                    cache_key = strategy.get_key(link.url_hash)
                    cache_data[cache_key] = link_dict
                elif name == "redirect":
                    cache_key = strategy.get_key(link.short_code)
                    cache_data[cache_key] = link.original_url
                elif name == "info":
                    cache_key = strategy.get_key(link.short_code)
                    cache_data[cache_key] = link_dict
        if cache_data:
            success = self._cache_client.set_many(cache_data, ttl)

        duration = (datetime.now() - start_time).total_seconds()
        self._log_info(
            "Завершение массового кэширования",
            success=success,
            duration_seconds=duration,
            links_per_second=link_count / duration if duration > 0 else 0,
        )

        return success

    def cache_service_stats(
        self,
        stats: Dict[str, Any],
        strategy: Optional[CacheKeyStrategy] = None,
        ttl: int = 300,
    ) -> bool:
        """Кэширование статистики использования сервиса ссылок"""
        if not self._cache_client or not strategy:
            return False

        cache_key = strategy.get_key()
        return self._cache_client.set(cache_key, stats, ttl)

    def invalidate_link(
        self, link: Link, strategies: Dict[str, CacheKeyStrategy]
    ) -> bool:
        """Инвалидация кэша ссылки"""
        if not self._cache_client:
            return False

        keys_to_delete = []

        for name, strategy in strategies.items():
            if name == "hash":
                keys_to_delete.append(strategy.get_key(link.url_hash))
            elif name == "redirect":
                keys_to_delete.append(strategy.get_key(link.short_code))
            elif name == "info":
                keys_to_delete.append(strategy.get_key(link.short_code))

        success = True
        for key in keys_to_delete:
            if not self._cache_client.delete(key):
                success = False

        return success

    def get_service_stats(
        self, strategy: Optional[CacheKeyStrategy] = None
    ) -> Optional[Dict[str, Any]]:
        """Получение статистики использования сервиса ссылок"""
        if not self._cache_client or not strategy:
            return None
        cache_key = strategy.get_key()
        cached_data = self._cache_client.get(cache_key)
        return cached_data

    def get_cache_stats(self) -> Optional[Dict[str, Any]]:
        """Получение статистики использования кэша"""
        if not self._cache_client:
            return None

        cache_data = self._cache_client.get_cache_stats()

        if cache_data:
            return cache_data
        return None
